import hashlib
import ipaddress
import json
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import ParseResult, unquote, urlparse

import urllib3
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from oauth2_provider.models import AbstractApplication, get_application_model
from oauth2_provider.oauth2_validators import OAuth2Validator
from requests.certs import where as default_ca_bundle_path
from urllib3.exceptions import HTTPError
from urllib3.response import HTTPResponse

from oauth_integrations.models import OAuthClientMetadata

CIMD_APP_PREFIX = "cimd:"
# Default cache lifetime used when the metadata response carries no usable cache headers.
CIMD_CACHE_SECONDS = 86400
# Bounds applied to any cache lifetime derived from HTTP cache headers.
CIMD_CACHE_MIN_SECONDS = 300
CIMD_CACHE_MAX_SECONDS = 86400
CIMD_FETCH_TIMEOUT_SECONDS = 3
CIMD_MAX_BODY_BYTES = 5 * 1024
CIMD_ALLOWED_CONTENT_TYPES = {"application/json"}
CIMD_ALLOWED_CONTENT_ENCODINGS = {"identity", *HTTPResponse.CONTENT_DECODERS}


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


@dataclass(frozen=True)
class ValidatedFetchURL:
    parsed: ParseResult
    address: str


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


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        return False
    return True


def _port_or_none(parsed) -> int | None:
    try:
        return parsed.port
    except ValueError:
        return None


def _require_valid_port(parsed) -> int | None:
    try:
        return parsed.port
    except ValueError as exc:
        raise CIMDError("CIMD URL must include a valid port.") from exc


def _is_debug_loopback_http_url(parsed) -> bool:
    return bool(
        settings.DEBUG
        and parsed.scheme == "http"
        and parsed.netloc
        and parsed.hostname
        and _port_or_none(parsed)
        and not _is_ip_literal(parsed.hostname)
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


def _validate_domain_hostname(hostname: str) -> str:
    hostname = hostname.strip().lower()
    if _is_ip_literal(hostname):
        raise CIMDError("CIMD metadata URL must use a domain name, not an IP address.")
    if hostname.endswith("."):
        raise CIMDError("CIMD metadata URL must use a normalized domain name.")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        raise CIMDError("CIMD metadata URL must not use localhost.")
    try:
        hostname.encode("ascii")
    except UnicodeEncodeError as exc:
        raise CIMDError("CIMD metadata URL must use an ASCII domain name.") from exc
    if len(hostname) > 253 or "." not in hostname:
        raise CIMDError("CIMD metadata URL must use a fully qualified domain name.")
    labels = hostname.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not re.fullmatch(r"[a-z0-9-]+", label)
        for label in labels
    ):
        raise CIMDError("CIMD metadata URL must use a valid domain name.")
    return hostname


def _path_contains_dot_segment(path: str) -> bool:
    decoded = path.replace("\\", "/")
    for _ in range(3):
        next_decoded = unquote(decoded).replace("\\", "/")
        if next_decoded == decoded:
            break
        decoded = next_decoded
    return any(segment in (".", "..") for segment in decoded.split("/"))


def _validate_fetch_url(client_id_url: str) -> ValidatedFetchURL:
    parsed = urlparse(client_id_url)
    if not parsed.hostname:
        raise CIMDError("CIMD client_id must include a hostname.")
    port = _require_valid_port(parsed)
    hostname = parsed.hostname.strip().lower()
    if _is_ip_literal(hostname):
        raise CIMDError("CIMD metadata URL must use a domain name, not an IP address.")
    is_debug_loopback_http_url = _is_debug_loopback_http_url(parsed)
    if parsed.scheme != "https" and not is_debug_loopback_http_url:
        if settings.DEBUG:
            raise CIMDError(
                "CIMD client_id must be an HTTPS URL."
                "During local development you can also use an HTTP URL with a loopback hostname and port."
            )
        raise CIMDError("CIMD client_id must be an HTTPS URL.")
    if parsed.username or parsed.password:
        raise CIMDError("CIMD client_id must not include user info.")
    if parsed.fragment:
        raise CIMDError("CIMD client_id must not include a fragment.")
    if parsed.params:
        raise CIMDError("CIMD client_id metadata URL must not include params.")
    if parsed.path in ("", "/"):
        raise CIMDError("CIMD client_id must point to a metadata document path.")
    if _path_contains_dot_segment(parsed.path):
        raise CIMDError("CIMD client_id must not contain single-dot or double-dot path segments.")

    if not is_debug_loopback_http_url:
        hostname = _validate_domain_hostname(hostname)
        if port not in (None, 443):
            raise CIMDError("CIMD metadata URL must use the default HTTPS port.")

        try:
            infos = socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise CIMDError("Could not resolve CIMD metadata hostname.") from exc

        addresses = {info[4][0] for info in infos}
        if not addresses:
            raise CIMDError("Could not resolve CIMD metadata hostname.")
        if any(_is_blocked_ip(str(address)) for address in addresses):
            raise CIMDError("CIMD metadata URL must not resolve to a private address.")
    else:
        try:
            infos = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise CIMDError("Could not resolve CIMD metadata hostname.") from exc
        addresses = {info[4][0] for info in infos}
        if not addresses:
            raise CIMDError("Could not resolve CIMD metadata hostname.")

    return ValidatedFetchURL(parsed=parsed, address=sorted(addresses)[0])


def _validate_https_uri(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CIMDError(f"{field_name} must be a non-empty string.")
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.netloc) and not _is_debug_loopback_http_url(parsed):
        raise CIMDError(f"{field_name} must be an HTTPS URL, except loopback HTTP in local development.")
    if parsed.username or parsed.password or parsed.fragment:
        raise CIMDError(f"{field_name} must not include user info or a fragment.")
    return value


def _origin(value: str) -> tuple[str, str, int | None]:
    parsed = urlparse(value)
    default_port = 443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None
    return (parsed.scheme, (parsed.hostname or "").lower(), _port_or_none(parsed) or default_port)


def _same_origin(a: str, b: str) -> bool:
    return _origin(a) == _origin(b)


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


def _request_target(parsed) -> str:
    target = parsed.path or "/"
    if parsed.params:
        target = f"{target};{parsed.params}"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return target


def _host_header(parsed) -> str:
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = 443 if parsed.scheme == "https" else 80
    port = _require_valid_port(parsed)
    if port and port != default_port:
        return f"{hostname}:{port}"
    return hostname


def _fetch_pinned_metadata_document(fetch_url: ValidatedFetchURL) -> tuple[int, dict[str, str], bytes]:
    parsed = fetch_url.parsed
    port = _require_valid_port(parsed) or (443 if parsed.scheme == "https" else 80)
    headers = {
        "Host": _host_header(parsed),
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
        "User-Agent": "testownik-cimd-fetcher/1.0",
    }
    timeout = urllib3.Timeout(connect=CIMD_FETCH_TIMEOUT_SECONDS, read=CIMD_FETCH_TIMEOUT_SECONDS)
    if parsed.scheme == "https":
        pool = urllib3.HTTPSConnectionPool(
            fetch_url.address,
            port=port,
            timeout=timeout,
            retries=False,
            maxsize=1,
            block=True,
            cert_reqs="CERT_REQUIRED",
            ca_certs=default_ca_bundle_path(),
            assert_hostname=parsed.hostname,
            server_hostname=parsed.hostname,
            ssl_minimum_version=ssl.TLSVersion.TLSv1_2,
        )
    else:
        pool = urllib3.HTTPConnectionPool(
            fetch_url.address,
            port=port,
            timeout=timeout,
            retries=False,
            maxsize=1,
            block=True,
        )

    response = None
    try:
        response = pool.urlopen(
            "GET",
            _request_target(parsed),
            headers=headers,
            preload_content=False,
            decode_content=True,
            redirect=False,
            retries=False,
        )
        response_headers = _validate_metadata_response_headers(response.headers)
        body = response.read(CIMD_MAX_BODY_BYTES + 1, decode_content=True)
        if len(body) > CIMD_MAX_BODY_BYTES:
            raise CIMDError("CIMD metadata response is too large.")
        return response.status, response_headers, body
    finally:
        if response is not None:
            response.close()
            response.release_conn()
        pool.close()


def _validate_metadata_response_headers(headers) -> dict[str, str]:
    normalized = {name.lower(): value.strip() for name, value in headers.items()}
    transfer_encoding = normalized.get("transfer-encoding", "").lower()
    transfer_encodings = [
        value.strip().lower()
        for header_value in headers.getlist("transfer-encoding", [])
        for value in header_value.split(",")
        if value.strip()
    ]
    if transfer_encodings and transfer_encodings != ["chunked"]:
        raise CIMDError("CIMD metadata response uses an unsupported transfer encoding.")
    content_encodings = [
        value.strip().lower()
        for header_value in headers.getlist("content-encoding", [])
        for value in header_value.split(",")
        if value.strip()
    ]
    unsupported_content_encodings = [
        encoding for encoding in content_encodings if encoding not in CIMD_ALLOWED_CONTENT_ENCODINGS
    ]
    if unsupported_content_encodings:
        raise CIMDError("CIMD metadata response uses an unsupported content encoding.")

    content_lengths = [value.strip() for value in headers.getlist("content-length", [])]
    if transfer_encoding and content_lengths:
        raise CIMDError("CIMD metadata response must not mix Transfer-Encoding and Content-Length.")
    if len(set(content_lengths)) > 1:
        raise CIMDError("CIMD metadata response has conflicting Content-Length headers.")
    if content_lengths:
        try:
            content_length = int(content_lengths[0])
        except ValueError as exc:
            raise CIMDError("CIMD metadata response has an invalid Content-Length header.") from exc
        if content_length > CIMD_MAX_BODY_BYTES:
            raise CIMDError("CIMD metadata response is too large.")

    content_type = normalized.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in CIMD_ALLOWED_CONTENT_TYPES and not content_type.endswith("+json"):
        raise CIMDError("CIMD metadata response must be JSON.")
    return normalized


def _clamp_cache_seconds(seconds: int) -> int:
    return max(CIMD_CACHE_MIN_SECONDS, min(seconds, CIMD_CACHE_MAX_SECONDS))


def _cache_seconds_from_headers(headers: dict[str, str]) -> int:
    cache_control = headers.get("cache-control", "").lower()
    if cache_control:
        directives = {}
        for token in cache_control.split(","):
            name, _, value = token.strip().partition("=")
            if name:
                directives[name] = value.strip()
        if "no-store" in directives or "no-cache" in directives:
            return CIMD_CACHE_MIN_SECONDS
        if "max-age" in directives:
            try:
                return _clamp_cache_seconds(int(directives["max-age"]))
            except ValueError:
                return CIMD_CACHE_SECONDS

    expires = headers.get("expires")
    if expires:
        try:
            expires_at = parsedate_to_datetime(expires)
        except (TypeError, ValueError):
            expires_at = None
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            return _clamp_cache_seconds(int((expires_at - timezone.now()).total_seconds()))

    return CIMD_CACHE_SECONDS


def fetch_client_metadata(client_id_url: str) -> tuple[dict, int]:
    fetch_url = _validate_fetch_url(client_id_url)
    try:
        status_code, headers, body = _fetch_pinned_metadata_document(fetch_url)
        if status_code != 200:
            raise CIMDError("CIMD metadata request failed.")
        data = json.loads(body.decode("utf-8"))
        cache_seconds = _cache_seconds_from_headers(headers)
    except CIMDError:
        raise
    except (HTTPError, OSError, ssl.SSLError, UnicodeEncodeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CIMDError("Could not fetch CIMD metadata.") from exc

    if not isinstance(data, dict):
        raise CIMDError("CIMD metadata must be a JSON object.")
    return data, cache_seconds


def validate_client_metadata(client_id_url: str, metadata: dict) -> ValidatedClientMetadata:
    if metadata.get("client_id") != client_id_url:
        raise CIMDError("CIMD metadata client_id must exactly match the metadata document URL.")

    if "client_secret" in metadata or "client_secret_expires_at" in metadata:
        raise CIMDError("CIMD metadata must not include a client_secret.")

    client_name = metadata.get("client_name")
    if not isinstance(client_name, str) or not client_name.strip():
        raise CIMDError("CIMD metadata must include client_name.")
    # Strip C0/C1 control characters before the name is shown on the consent screen.
    client_name = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", client_name).strip()[:255]
    if not client_name:
        raise CIMDError("CIMD metadata must include client_name.")

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
        if not _same_origin(client_uri, client_id_url):
            raise CIMDError("client_uri must share the same origin as the client_id metadata URL.")

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

    metadata, cache_seconds = fetch_client_metadata(client_id_url)
    validated = validate_client_metadata(client_id_url, metadata)
    Application = get_application_model()
    internal_client_id = _internal_client_id(client_id_url)
    cache_expires_at = now + timedelta(seconds=cache_seconds)

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
