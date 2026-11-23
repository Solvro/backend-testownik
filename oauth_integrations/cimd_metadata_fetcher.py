import logging
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import DatabaseError, transaction
from django.utils import timezone
from oauth2_provider.cimd import SafeMetadataFetcher

from oauth_integrations.models import OAuthClientMetadata

logger = logging.getLogger(__name__)
url_validator = URLValidator(schemes=["http", "https"])

# The toolkit validates a fetched document (client_id binding, grant types,
# Application.full_clean) only after the fetcher returns, and saves the
# Application only when that validation passes. A fetched document is therefore
# held here and persisted from the Application post_save signal, so rejected
# documents never create or overwrite display metadata.
PENDING_METADATA_MAX_AGE = timedelta(seconds=60)


@dataclass(frozen=True)
class _PendingMetadata:
    client_id: str
    metadata: dict
    fetched_at: datetime
    expires_at: datetime


_pending_metadata: ContextVar[_PendingMetadata | None] = ContextVar("pending_cimd_metadata", default=None)


def _display_url(metadata, key, client_id):
    value = metadata.get(key, "")
    if not value:
        return ""
    if not isinstance(value, str):
        logger.warning("Ignoring invalid CIMD %s for %s: expected a URL string", key, client_id)
        return ""
    if len(value) > 2048:
        logger.warning("Ignoring invalid CIMD %s for %s: URL exceeds 2048 characters", key, client_id)
        return ""
    try:
        url_validator(value)
    except ValidationError as error:
        logger.warning("Ignoring invalid CIMD %s for %s: %s", key, client_id, error)
        return ""
    return value


class PersistingCIMDMetadataFetcher(SafeMetadataFetcher):
    def fetch(self, client_id):
        _pending_metadata.set(None)
        metadata, max_age = super().fetch(client_id)
        fetched_at = timezone.now()
        _pending_metadata.set(
            _PendingMetadata(
                client_id=client_id,
                metadata=metadata,
                fetched_at=fetched_at,
                expires_at=fetched_at + timedelta(seconds=max_age),
            )
        )
        return metadata, max_age


def _take_pending_metadata(application):
    pending = _pending_metadata.get()
    if pending is None or pending.client_id != application.client_id:
        return None
    _pending_metadata.set(None)
    if timezone.now() - pending.fetched_at > PENDING_METADATA_MAX_AGE:
        return None
    # The toolkit stamps cimd_expires_at from this fetch only when it accepts the
    # document. A save that keeps an older expiry (e.g. an admin edit after a
    # rejected refresh) must not pick up the rejected document.
    expires_at = application.cimd_expires_at
    if expires_at is None or abs(expires_at - pending.expires_at) > PENDING_METADATA_MAX_AGE:
        return None
    return pending


def persist_validated_cimd_metadata(sender, instance, **kwargs):
    """Store display metadata once the toolkit has accepted and saved a CIMD application."""
    if instance.registration_source != instance.RegistrationSource.CIMD:
        return
    pending = _take_pending_metadata(instance)
    if pending is None:
        return

    metadata = pending.metadata
    client_id = instance.client_id
    client_name = metadata.get("client_name", "")
    if not isinstance(client_name, str) or len(client_name) > 255:
        logger.warning("Ignoring invalid CIMD client_name for %s", client_id)
        client_name = ""

    record = (
        OAuthClientMetadata.objects.filter(application=instance).first()
        or OAuthClientMetadata.objects.filter(client_id_url=client_id).first()
        or OAuthClientMetadata()
    )
    record.application = instance
    record.client_id_url = client_id
    record.client_name = client_name
    record.client_uri = _display_url(metadata, "client_uri", client_id)
    record.logo_uri = _display_url(metadata, "logo_uri", client_id)
    record.redirect_uris = metadata.get("redirect_uris", [])
    record.grant_types = metadata.get("grant_types", [])
    record.response_types = metadata.get("response_types", [])
    record.token_endpoint_auth_method = metadata.get("token_endpoint_auth_method", "none")
    record.metadata = metadata
    record.fetched_at = pending.fetched_at
    record.cache_expires_at = pending.expires_at

    try:
        # Display metadata is best effort: a failure here must not undo the
        # toolkit's accepted application or poison an outer transaction.
        with transaction.atomic():
            record.save()
    except DatabaseError:
        logger.exception("Failed to persist CIMD display metadata for %s", client_id)
