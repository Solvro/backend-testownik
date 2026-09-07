import socket
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings

from uploads.image_sources import download_image_source


@override_settings(ALLOWED_IMAGE_SOURCE_HOSTS=["images.example.com"])
class ImageSourceDownloadTests(SimpleTestCase):
    def setUp(self):
        dns_patch = patch("uploads.image_sources.socket.getaddrinfo")
        self.dns = dns_patch.start()
        self.addCleanup(dns_patch.stop)
        self.dns.return_value = self.addresses("8.8.8.8")
        pool_patch = patch("uploads.image_sources.urllib3.HTTPSConnectionPool")
        self.pool_class = pool_patch.start()
        self.addCleanup(pool_patch.stop)
        self.pool = self.pool_class.return_value
        self.response = self.pool.urlopen.return_value
        self.response.status = 200
        self.response.headers = {"Content-Type": "image/avif"}
        self.response.read.return_value = b"image"

    @staticmethod
    def addresses(*addresses):
        return [
            (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses
        ]

    def download(self, url="https://images.example.com/photo.avif?seed=test#fragment"):
        return download_image_source(url, max_size=10, timeout=5)

    def test_pins_connection_and_preserves_tls_hostname_host_and_query(self):
        self.assertEqual(self.download(), (b"image", "image/avif"))
        self.dns.assert_called_once_with("images.example.com", 443, type=socket.SOCK_STREAM)
        self.assertEqual(self.pool_class.call_args.args, ("8.8.8.8",))
        options = self.pool_class.call_args.kwargs
        self.assertEqual(options["server_hostname"], "images.example.com")
        self.assertEqual(options["assert_hostname"], "images.example.com")
        self.assertEqual(options["cert_reqs"], "CERT_REQUIRED")
        self.assertTrue(options["ca_certs"])
        self.assertEqual(self.pool.urlopen.call_args.args, ("GET", "/photo.avif?seed=test"))
        self.assertEqual(self.pool.urlopen.call_args.kwargs["headers"]["Host"], "images.example.com")
        self.assertFalse(self.pool.urlopen.call_args.kwargs["redirect"])
        self.assertFalse(self.pool.urlopen.call_args.kwargs["retries"])
        self.response.read.assert_called_once_with(11, decode_content=False)
        self.response.close.assert_called_once()
        self.response.release_conn.assert_called_once()
        self.pool.close.assert_called_once()

    def test_rejects_any_non_public_dns_answer_including_mixed_answers(self):
        for address in (
            "127.0.0.1",
            "10.0.0.1",
            "169.254.169.254",
            "0.0.0.0",
            "224.0.0.1",
            "::1",
            "fe80::1",
            "fc00::1",
            "::ffff:127.0.0.1",
        ):
            with self.subTest(address=address):
                self.dns.return_value = self.addresses("8.8.8.8", address)
                with self.assertRaises(ValidationError):
                    self.download()
        self.pool_class.assert_not_called()

    def test_accepts_public_ipv6(self):
        self.dns.return_value = self.addresses("2606:4700:4700::1111")
        self.download()
        self.assertEqual(self.pool_class.call_args.args, ("2606:4700:4700::1111",))

    def test_fails_closed_on_dns_failure_or_empty_answers(self):
        self.dns.return_value = []
        with self.assertRaises(ValidationError):
            self.download()
        self.dns.side_effect = socket.gaierror("unavailable")
        with self.assertRaises(ValidationError):
            self.download()
        self.pool_class.assert_not_called()

    def test_rejects_disallowed_and_malformed_urls_before_dns(self):
        for url in (
            "https://evil.example/photo",
            "https://images.example.com:invalid/photo",
            "https://user:secret@images.example.com/photo",
            "https://[invalid/photo",
            "https://images.example.com/\nphoto",
        ):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                self.download(url)
        self.dns.assert_not_called()

    def test_http_uses_pinned_address_and_preserves_custom_port(self):
        with patch("uploads.image_sources.urllib3.HTTPConnectionPool") as http_pool:
            http_pool.return_value.urlopen.return_value = self.response
            self.download("http://images.example.com:8080/photo")
        self.assertEqual(http_pool.call_args.args, ("8.8.8.8",))
        self.assertEqual(http_pool.call_args.kwargs["port"], 8080)
        self.assertEqual(http_pool.return_value.urlopen.call_args.kwargs["headers"]["Host"], "images.example.com:8080")
        self.pool_class.assert_not_called()

    def test_rejects_redirect_and_closes_response_without_reading(self):
        self.response.status = 302
        with self.assertRaises(ValueError):
            self.download()
        self.response.read.assert_not_called()
        self.response.close.assert_called_once()
        self.pool.close.assert_called_once()

    def test_rejects_oversized_body_without_content_length(self):
        self.response.read.return_value = b"x" * 11
        with self.assertRaises(ValueError):
            self.download()
        self.response.close.assert_called_once()
        self.pool.close.assert_called_once()

    def test_rejects_oversized_or_invalid_length_and_compression_before_reading(self):
        for headers in ({"Content-Length": "11"}, {"Content-Length": "invalid"}, {"Content-Encoding": "gzip"}):
            with self.subTest(headers=headers):
                self.response.headers = headers
                with self.assertRaises(ValueError):
                    self.download()
        self.response.read.assert_not_called()

    def test_closes_pool_when_request_fails(self):
        self.pool.urlopen.side_effect = OSError("connection failed")
        with self.assertRaises(OSError):
            self.download()
        self.pool.close.assert_called_once()

    def test_worker_and_backfill_use_shared_transport(self):
        from users.management.commands.backfill_user_photos import Command
        from users.views.oauth import _sync_download_photo

        transport = Mock(return_value=(b"image", "image/avif"))
        with patch("users.views.oauth.download_image_source", transport):
            self.assertEqual(_sync_download_photo("https://images.example.com/photo", 123), transport.return_value)
        transport.assert_called_once_with("https://images.example.com/photo", max_size=123, timeout=5)
        transport.reset_mock()
        with patch("users.management.commands.backfill_user_photos.download_image_source", transport):
            self.assertEqual(Command()._download("https://images.example.com/photo", 7), transport.return_value)
        transport.assert_called_once_with("https://images.example.com/photo", max_size=10 * 1024 * 1024, timeout=7)
