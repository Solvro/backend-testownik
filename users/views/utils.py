import logging
import re
import urllib.parse
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django.conf import settings
from django.utils.http import url_has_allowed_host_and_scheme

from testownik_core.settings import (
    ALLOW_PREVIEW_ENVIRONMENTS,
    ALLOWED_REDIRECT_ORIGINS,
    PREVIEW_ORIGIN_REGEXES,
)

logger = logging.getLogger(__name__)


def add_query_params(url, params):
    url_parts = list(urlparse(url))
    query = dict(parse_qs(url_parts[4]))
    query.update(params)
    url_parts[4] = urlencode(query, doseq=True)
    return str(urlunparse(url_parts))


def remove_query_params(url, params):
    url_parts = list(urlparse(url))
    query = dict(parse_qs(url_parts[4]))
    for param in params:
        query.pop(param, None)
    url_parts[4] = urlencode(query, doseq=True)
    return str(urlunparse(url_parts))


def _usos_safe_quote(s, safe="", encoding=None, errors=None):
    return urllib.parse.quote(s, safe=":/@!$'()*+,;-._~")


def build_oauth_callback_url(request, path, params):
    """Build an OAuth callback URL with properly encoded query parameters.

    Uses a permissive quote function that preserves URL-safe characters
    like : and / while encoding only characters that break query-string
    parsing (& = ? #). This is required for OAuth 1.0a signature
    compatibility (USOS).
    """
    query_string = urlencode(params, quote_via=_usos_safe_quote)
    return request.build_absolute_uri(f"{path}?{query_string}")


def is_safe_redirect_url(url: str, request=None) -> bool:
    if not url:
        return False

    if url == "admin:index":
        return True

    url = str(url).strip()

    if url.startswith("//") or url.startswith("\\\\"):
        return False

    if url.startswith("/"):
        return True

    allowed_hosts = {urlparse(origin).netloc for origin in ALLOWED_REDIRECT_ORIGINS}
    if request:
        allowed_hosts.add(request.get_host())

    is_django_safe = url_has_allowed_host_and_scheme(
        url,
        allowed_hosts=allowed_hosts,
        require_https=not getattr(settings, "DEBUG", False),
    )

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        if not parsed.netloc:
            return False

        url_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

        if is_django_safe:
            if url_origin in ALLOWED_REDIRECT_ORIGINS:
                return True
            if request and parsed.netloc == request.get_host():
                return True

        if ALLOW_PREVIEW_ENVIRONMENTS:
            for regex in PREVIEW_ORIGIN_REGEXES:
                if re.match(regex, url_origin):
                    return True

        return False
    except Exception:
        return False


def get_safe_redirect_url(url: str, request=None, default="index") -> str:
    if not url:
        return default
    if not is_safe_redirect_url(url, request):
        if url:
            logger.warning("Blocked unsafe redirect URL: %s", url)
        return default
    return url
