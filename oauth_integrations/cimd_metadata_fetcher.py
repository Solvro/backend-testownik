import logging
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils import timezone
from oauth2_provider.cimd import SafeMetadataFetcher

from oauth_integrations.models import OAuthClientMetadata

logger = logging.getLogger(__name__)
url_validator = URLValidator(schemes=["http", "https"])


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
        metadata, max_age = super().fetch(client_id)
        fetched_at = timezone.now()
        client_name = metadata.get("client_name", "")
        if not isinstance(client_name, str) or len(client_name) > 255:
            logger.warning("Ignoring invalid CIMD client_name for %s", client_id)
            client_name = ""

        OAuthClientMetadata.objects.update_or_create(
            client_id_url=client_id,
            defaults={
                "client_name": client_name,
                "client_uri": _display_url(metadata, "client_uri", client_id),
                "logo_uri": _display_url(metadata, "logo_uri", client_id),
                "redirect_uris": metadata.get("redirect_uris", []),
                "grant_types": metadata.get("grant_types", []),
                "response_types": metadata.get("response_types", []),
                "token_endpoint_auth_method": metadata.get("token_endpoint_auth_method", "none"),
                "metadata": metadata,
                "fetched_at": fetched_at,
                "cache_expires_at": fetched_at + timedelta(seconds=max_age),
            },
        )
        return metadata, max_age
