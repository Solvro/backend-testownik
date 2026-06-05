import socket
from unittest.mock import patch
from urllib.parse import urlparse

from django.test import SimpleTestCase, override_settings
from urllib3 import HTTPHeaderDict

from oauth_integrations.oauth_cimd import (
    CIMD_CACHE_SECONDS,
    CIMD_MAX_BODY_BYTES,
    CIMDError,
    ValidatedFetchURL,
    _validate_fetch_url,
    _validate_metadata_response_headers,
    fetch_client_metadata,
    validate_client_metadata,
)


def _addrinfo(address):
    return [(None, None, None, "", (address, 443))]


class CIMDValidationTests(SimpleTestCase):
    @override_settings(DEBUG=False)
    def test_validate_fetch_url_rejects_private_ip_literal(self):
        with self.assertRaisesMessage(CIMDError, "domain name"):
            _validate_fetch_url("https://127.0.0.1/.well-known/oauth-client")

    @override_settings(DEBUG=False)
    def test_validate_fetch_url_rejects_public_ip_literal(self):
        with self.assertRaisesMessage(CIMDError, "domain name"):
            _validate_fetch_url("https://8.8.8.8/.well-known/oauth-client")

    @override_settings(DEBUG=False)
    @patch("oauth_integrations.oauth_cimd.socket.getaddrinfo", return_value=_addrinfo("10.0.0.5"))
    def test_validate_fetch_url_rejects_private_dns_result(self, mock_getaddrinfo):
        with self.assertRaisesMessage(CIMDError, "private address"):
            _validate_fetch_url("https://client.example/.well-known/oauth-client")

        mock_getaddrinfo.assert_called_once_with("client.example", 443, type=socket.SOCK_STREAM)

    @override_settings(DEBUG=False)
    @patch("oauth_integrations.oauth_cimd.socket.getaddrinfo", return_value=_addrinfo("8.8.8.8"))
    def test_validate_fetch_url_returns_pinned_public_address(self, mock_getaddrinfo):
        fetch_url = _validate_fetch_url("https://client.example/.well-known/oauth-client")

        self.assertEqual(fetch_url.address, "8.8.8.8")
        self.assertEqual(fetch_url.parsed.hostname, "client.example")
        mock_getaddrinfo.assert_called_once_with("client.example", 443, type=socket.SOCK_STREAM)

    @override_settings(DEBUG=True)
    @patch("oauth_integrations.oauth_cimd.socket.getaddrinfo", return_value=_addrinfo("127.0.0.1"))
    def test_validate_fetch_url_allows_debug_loopback_http(self, mock_getaddrinfo):
        fetch_url = _validate_fetch_url("http://localhost:3333/oauth-client")

        self.assertEqual(fetch_url.address, "127.0.0.1")
        self.assertEqual(fetch_url.parsed.scheme, "http")
        mock_getaddrinfo.assert_called_once_with("localhost", 3333, type=socket.SOCK_STREAM)

    @override_settings(DEBUG=False)
    @patch("oauth_integrations.oauth_cimd._validate_fetch_url")
    @patch("oauth_integrations.oauth_cimd._fetch_pinned_metadata_document")
    def test_fetch_client_metadata_uses_validated_pinned_url(self, mock_fetch, mock_validate):
        mock_validate.return_value = ValidatedFetchURL(
            parsed=urlparse("https://client.example/.well-known/oauth-client"),
            address="8.8.8.8",
        )
        mock_fetch.return_value = (
            200,
            {"content-type": "application/json"},
            b'{"client_id":"https://client.example/.well-known/oauth-client"}',
        )

        data, cache_seconds = fetch_client_metadata("https://client.example/.well-known/oauth-client")

        self.assertEqual(data["client_id"], "https://client.example/.well-known/oauth-client")
        self.assertEqual(cache_seconds, CIMD_CACHE_SECONDS)
        mock_fetch.assert_called_once_with(mock_validate.return_value)

    @override_settings(DEBUG=False)
    def test_validate_fetch_url_rejects_encoded_dot_segments(self):
        with self.assertRaisesMessage(CIMDError, "dot"):
            _validate_fetch_url("https://client.example/%2e%2e/admin/oauth-client")

    @override_settings(DEBUG=False)
    def test_validate_fetch_url_rejects_query_string(self):
        with self.assertRaisesMessage(CIMDError, "query string"):
            _validate_fetch_url("https://client.example/.well-known/oauth-client?target=internal")

    @override_settings(DEBUG=False)
    def test_validate_fetch_url_rejects_invalid_port(self):
        with self.assertRaisesMessage(CIMDError, "valid port"):
            _validate_fetch_url("https://client.example:99999/.well-known/oauth-client")

    @override_settings(DEBUG=False)
    def test_validate_fetch_url_rejects_custom_https_port(self):
        with self.assertRaisesMessage(CIMDError, "default HTTPS port"):
            _validate_fetch_url("https://client.example:8443/.well-known/oauth-client")

    @override_settings(DEBUG=True)
    def test_validate_fetch_url_rejects_debug_loopback_ip_literal(self):
        with self.assertRaisesMessage(CIMDError, "domain name"):
            _validate_fetch_url("http://127.0.0.1:3333/oauth-client")

    def test_validate_metadata_response_headers_rejects_transfer_encoding(self):
        headers = HTTPHeaderDict({"content-type": "application/json", "transfer-encoding": "chunked"})

        with self.assertRaisesMessage(CIMDError, "transfer encoding"):
            _validate_metadata_response_headers(headers)

    def test_validate_metadata_response_headers_rejects_large_content_length(self):
        headers = HTTPHeaderDict(
            {
                "content-type": "application/json",
                "content-length": str(CIMD_MAX_BODY_BYTES + 1),
            }
        )

        with self.assertRaisesMessage(CIMDError, "too large"):
            _validate_metadata_response_headers(headers)

    def test_validate_metadata_response_headers_rejects_content_encoding(self):
        headers = HTTPHeaderDict({"content-type": "application/json", "content-encoding": "gzip"})

        with self.assertRaisesMessage(CIMDError, "content encoding"):
            _validate_metadata_response_headers(headers)

    @override_settings(DEBUG=False)
    def test_validate_client_metadata_rejects_confidential_client(self):
        metadata = {
            "client_id": "https://client.example/.well-known/oauth-client",
            "client_name": "Example",
            "redirect_uris": ["https://client.example/callback"],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_basic",
        }

        with self.assertRaisesMessage(CIMDError, "public PKCE"):
            validate_client_metadata("https://client.example/.well-known/oauth-client", metadata)

    @override_settings(DEBUG=False)
    def test_validate_fetch_url_rejects_dot_segments(self):
        with self.assertRaisesMessage(CIMDError, "dot"):
            _validate_fetch_url("https://client.example/../admin/oauth-client")

    @override_settings(DEBUG=False)
    def test_validate_client_metadata_rejects_cross_origin_client_uri(self):
        metadata = {
            "client_id": "https://client.example/.well-known/oauth-client",
            "client_name": "Example",
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none",
            "client_uri": "https://attacker.example/",
        }

        with self.assertRaisesMessage(CIMDError, "same origin"):
            validate_client_metadata("https://client.example/.well-known/oauth-client", metadata)

    @override_settings(DEBUG=False)
    def test_validate_client_metadata_rejects_client_secret(self):
        metadata = {
            "client_id": "https://client.example/.well-known/oauth-client",
            "client_name": "Example",
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none",
            "client_secret": "leaked",
        }

        with self.assertRaisesMessage(CIMDError, "client_secret"):
            validate_client_metadata("https://client.example/.well-known/oauth-client", metadata)

    @override_settings(DEBUG=False)
    def test_validate_client_metadata_strips_control_chars_from_name(self):
        metadata = {
            "client_id": "https://client.example/.well-known/oauth-client",
            "client_name": "Evil\r\nApp\x00",
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none",
        }

        validated = validate_client_metadata("https://client.example/.well-known/oauth-client", metadata)

        self.assertEqual(validated.client_name, "EvilApp")

    @override_settings(DEBUG=False)
    def test_validate_client_metadata_accepts_public_pkce_client(self):
        metadata = {
            "client_id": "https://client.example/.well-known/oauth-client",
            "client_name": "Example",
            "redirect_uris": ["https://client.example/callback"],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }

        validated = validate_client_metadata("https://client.example/.well-known/oauth-client", metadata)

        self.assertEqual(validated.client_name, "Example")
        self.assertEqual(validated.redirect_uris, ["https://client.example/callback"])
