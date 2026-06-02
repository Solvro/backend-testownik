import hashlib
import ipaddress
import json
import socket
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from oauth2_provider.models import AbstractApplication, get_application_model
from oauth2_provider.oauth2_validators import OAuth2Validator

from oauth_integrations.models import OAuthClientMetadata

CIMD_APP_PREFIX = "cimd:"
CIMD_CACHE_SECONDS = 86400
CIMD_FETCH_TIMEOUT_SECONDS = 3
CIMD_MAX_BODY_BYTES = 64 * 1024


class CIMDError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedClientMetadata:
    client_id_url: str
    client_name: str
    client_uri: str
    logo_uri: str
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[str]
    token_endpoint_auth_method: str
    metadata: dict


def is_cimd_client_id(client_id: str | None) -> bool:
    if not client_id:
        return False
    parsed = urlparse(client_id)
    return (parsed.scheme == "https" and bool(parsed.netloc)) or _is_debug_loopback_http_url(parsed)


def _is_loopback_hostname(hostname: str) -> bool:
    hostname = hostname.strip().lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _is_debug_loopback_http_url(parsed) -> bool:
    return bool(
        settings.DEBUG
        and parsed.scheme == "http"
        and parsed.netloc
        and parsed.hostname
        and parsed.port
        and _is_loopback_hostname(parsed.hostname)
    )


def _is_blocked_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_unspecified,
            ip.is_reserved,
        )
    )


def _validate_fetch_url(client_id_url: str) -> str:
    parsed = urlparse(client_id_url)
    is_debug_loopback_http_url = _is_debug_loopback_http_url(parsed)
    if parsed.scheme != "https" and not is_debug_loopback_http_url:
        if settings.DEBUG:
            raise CIMDError(
                "CIMD client_id must be an HTTPS URL."
                "During local development you can also use an HTTP URL with a loopback hostname and port."
            )
        raise CIMDError("CIMD client_id must be an HTTPS URL.")
    if not parsed.hostname:
        raise CIMDError("CIMD client_id must include a hostname.")
    if parsed.username or parsed.password:
        raise CIMDError("CIMD client_id must not include user info.")
    if parsed.fragment:
        raise CIMDError("CIMD client_id must not include a fragment.")
    if parsed.path in ("", "/"):
        raise CIMDError("CIMD client_id must point to a metadata document path.")

    # Gate on the allowlist before resolving DNS so that non-allowlisted,
    # caller-supplied hostnames never trigger a lookup. The matched value is
    # returned from settings (not the caller input) so the fetched URL is not
    # attacker-controlled.
    allowlisted_url = next(
        (url for url in getattr(settings, "CIMD_ALLOWED_CLIENT_METADATA_URLS", []) if url == client_id_url),
        None,
    )
    if allowlisted_url is None:
        raise CIMDError("CIMD metadata URL is not allowlisted.")

    if not is_debug_loopback_http_url:
        hostname = parsed.hostname.strip().lower()
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
            raise CIMDError("CIMD metadata URL must not use localhost.")

        try:
            if _is_blocked_ip(hostname):
                raise CIMDError("CIMD metadata URL must not resolve to a private address.")
        except ValueError:
            pass

        try:
            infos = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise CIMDError("Could not resolve CIMD metadata hostname.") from exc

        addresses = {info[4][0] for info in infos}
        if not addresses:
            raise CIMDError("Could not resolve CIMD metadata hostname.")
        if any(_is_blocked_ip(str(address)) for address in addresses):
            raise CIMDError("CIMD metadata URL must not resolve to a private address.")

    return allowlisted_url


def _validate_https_uri(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CIMDError(f"{field_name} must be a non-empty string.")
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.netloc) and not _is_debug_loopback_http_url(parsed):
        raise CIMDError(f"{field_name} must be an HTTPS URL, except loopback HTTP in local development.")
    if parsed.username or parsed.password or parsed.fragment:
        raise CIMDError(f"{field_name} must not include user info or a fragment.")
    return value


def _validate_redirect_uri(uri: str) -> str:
    if not isinstance(uri, str) or not uri:
        raise CIMDError("redirect_uris must contain non-empty strings.")
    parsed = urlparse(uri)
    if parsed.username or parsed.password or parsed.fragment:
        raise CIMDError("redirect_uris must not include user info or a fragment.")
    if parsed.scheme == "https" and parsed.netloc:
        return uri
    if parsed.scheme == "http" and parsed.hostname and _is_loopback_hostname(parsed.hostname):
        return uri
    if settings.DEBUG and parsed.scheme == "http" and parsed.netloc:
        return uri
    raise CIMDError("redirect_uris must be HTTPS, except loopback HTTP callbacks.")


def _redirect_uri_matches_registered(registered_uri: str, redirect_uri: str) -> bool:
    if redirect_uri == registered_uri:
        return True

    registered = urlparse(registered_uri)
    requested = urlparse(redirect_uri)
    if (
        registered.scheme != "http"
        or requested.scheme != "http"
        or not registered.hostname
        or not requested.hostname
        or not _is_loopback_hostname(registered.hostname)
        or not _is_loopback_hostname(requested.hostname)
        or registered.hostname.lower() != requested.hostname.lower()
        or registered.port is not None
        or requested.port is None
        or registered.username
        or registered.password
        or requested.username
        or requested.password
        or registered.fragment
        or requested.fragment
    ):
        return False

    return (
        registered.path == requested.path
        and registered.params == requested.params
        and registered.query == requested.query
    )


def fetch_client_metadata(client_id_url: str) -> dict:
    metadata_url = _validate_fetch_url(client_id_url)
    try:
        response = requests.get(
            metadata_url,
            timeout=CIMD_FETCH_TIMEOUT_SECONDS,
            allow_redirects=False,
            headers={"Accept": "application/json"},
            stream=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type.lower():
            raise CIMDError("CIMD metadata response must be JSON.")
        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=8192):
            total += len(chunk)
            if total > CIMD_MAX_BODY_BYTES:
                raise CIMDError("CIMD metadata response is too large.")
            chunks.append(chunk)
        data = json.loads(b"".join(chunks).decode(response.encoding or "utf-8"))
    except CIMDError:
        raise
    except (requests.RequestException, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CIMDError("Could not fetch CIMD metadata.") from exc

    if not isinstance(data, dict):
        raise CIMDError("CIMD metadata must be a JSON object.")
    return data


def validate_client_metadata(client_id_url: str, metadata: dict) -> ValidatedClientMetadata:
    if metadata.get("client_id") != client_id_url:
        raise CIMDError("CIMD metadata client_id must exactly match the metadata document URL.")

    client_name = metadata.get("client_name")
    if not isinstance(client_name, str) or not client_name.strip():
        raise CIMDError("CIMD metadata must include client_name.")
    client_name = client_name.strip()[:255]

    redirect_uris_raw = metadata.get("redirect_uris")
    if not isinstance(redirect_uris_raw, list) or not redirect_uris_raw:
        raise CIMDError("CIMD metadata must include non-empty redirect_uris.")
    redirect_uris = [_validate_redirect_uri(uri) for uri in redirect_uris_raw]

    grant_types = metadata.get("grant_types") or ["authorization_code"]
    if not isinstance(grant_types, list) or "authorization_code" not in grant_types:
        raise CIMDError("CIMD clients must support authorization_code.")

    response_types = metadata.get("response_types") or ["code"]
    if not isinstance(response_types, list) or "code" not in response_types:
        raise CIMDError("CIMD clients must support code response type.")

    token_endpoint_auth_method = metadata.get("token_endpoint_auth_method", "none")
    if token_endpoint_auth_method != "none":
        raise CIMDError("Only public PKCE CIMD clients are supported.")

    client_uri = metadata.get("client_uri") or ""
    if client_uri:
        client_uri = _validate_https_uri(client_uri, "client_uri")

    logo_uri = metadata.get("logo_uri") or ""
    if logo_uri:
        logo_uri = _validate_https_uri(logo_uri, "logo_uri")

    return ValidatedClientMetadata(
        client_id_url=client_id_url,
        client_name=client_name,
        client_uri=client_uri,
        logo_uri=logo_uri,
        redirect_uris=redirect_uris,
        grant_types=grant_types,
        response_types=response_types,
        token_endpoint_auth_method=token_endpoint_auth_method,
        metadata=metadata,
    )


def _internal_client_id(client_id_url: str) -> str:
    digest = hashlib.sha256(client_id_url.encode()).hexdigest()[:48]
    return f"{CIMD_APP_PREFIX}{digest}"


def get_cimd_metadata_for_application(application) -> OAuthClientMetadata | None:
    if application is None:
        return None
    try:
        return application.cimd_metadata
    except OAuthClientMetadata.DoesNotExist:
        return None


def get_or_create_cimd_application(client_id_url: str, *, force_refresh: bool = False):
    metadata_record = (
        OAuthClientMetadata.objects.select_related("application").filter(client_id_url=client_id_url).first()
    )
    now = timezone.now()
    if metadata_record and not force_refresh:
        expires_at = metadata_record.cache_expires_at
        if expires_at is None or expires_at > now:
            return metadata_record.application

    validated = validate_client_metadata(client_id_url, fetch_client_metadata(client_id_url))
    Application = get_application_model()
    internal_client_id = _internal_client_id(client_id_url)
    cache_expires_at = now + timedelta(seconds=CIMD_CACHE_SECONDS)

    with transaction.atomic():
        application, _ = Application.objects.update_or_create(
            client_id=internal_client_id,
            defaults={
                "name": validated.client_name,
                "client_type": AbstractApplication.CLIENT_PUBLIC,
                "authorization_grant_type": AbstractApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": " ".join(validated.redirect_uris),
                "client_secret": "",
                "skip_authorization": False,
            },
        )
        OAuthClientMetadata.objects.update_or_create(
            client_id_url=client_id_url,
            defaults={
                "application": application,
                "client_name": validated.client_name,
                "client_uri": validated.client_uri,
                "logo_uri": validated.logo_uri,
                "redirect_uris": validated.redirect_uris,
                "grant_types": validated.grant_types,
                "response_types": validated.response_types,
                "token_endpoint_auth_method": validated.token_endpoint_auth_method,
                "metadata": validated.metadata,
                "fetched_at": now,
                "cache_expires_at": cache_expires_at,
            },
        )
    return application


def resolve_application_from_public_client_id(client_id: str, *, force_refresh: bool = False):
    Application = get_application_model()
    try:
        return Application.objects.get(client_id=client_id)
    except Application.DoesNotExist:
        if not is_cimd_client_id(client_id):
            return None
    try:
        return get_or_create_cimd_application(client_id, force_refresh=force_refresh)
    except (CIMDError, ValidationError):
        return None


class CIMDOAuth2Validator(OAuth2Validator):
    def _load_application(self, client_id, request):
        if request.client:
            metadata = get_cimd_metadata_for_application(request.client)
            if metadata and metadata.client_id_url == client_id and request.client.is_usable(request):
                return request.client

        application = super()._load_application(client_id, request)
        if application is not None:
            return application

        if not is_cimd_client_id(client_id):
            return None

        try:
            application = get_or_create_cimd_application(client_id)
        except CIMDError:
            return None
        if not application.is_usable(request):
            return None
        request.client = application
        request.cimd_client_id_url = client_id
        return application

    def validate_redirect_uri(self, client_id, redirect_uri, request, *args, **kwargs):
        metadata = get_cimd_metadata_for_application(request.client)
        if metadata:
            if metadata.cache_expires_at and metadata.cache_expires_at <= timezone.now():
                try:
                    request.client = get_or_create_cimd_application(metadata.client_id_url, force_refresh=True)
                    metadata = get_cimd_metadata_for_application(request.client)
                except CIMDError:
                    return False
            return any(_redirect_uri_matches_registered(uri, redirect_uri) for uri in metadata.redirect_uris)
        return super().validate_redirect_uri(client_id, redirect_uri, request, *args, **kwargs)

    def get_default_redirect_uri(self, client_id, request, *args, **kwargs):
        metadata = get_cimd_metadata_for_application(request.client)
        if metadata and metadata.redirect_uris:
            return metadata.redirect_uris[0]
        return super().get_default_redirect_uri(client_id, request, *args, **kwargs)

    def authenticate_client_id(self, client_id, request, *args, **kwargs):
        if self._load_application(client_id, request) is not None:
            metadata = get_cimd_metadata_for_application(request.client)
            if metadata:
                return request.client.client_type == AbstractApplication.CLIENT_PUBLIC
            return request.client.client_type != AbstractApplication.CLIENT_CONFIDENTIAL
        return False
