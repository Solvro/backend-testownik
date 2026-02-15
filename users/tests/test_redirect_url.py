"""
Tests for is_safe_redirect_url function to prevent open redirect vulnerabilities.
"""

from unittest.mock import patch

from django.test import TestCase

from users.views import is_safe_redirect_url


class IsSafeRedirectUrlTestCase(TestCase):
    """Tests for the is_safe_redirect_url security function."""

    # --- VALID CASES ---

    def test_admin_index_view_name_is_safe(self):
        """The Django admin:index view name should be accepted as safe."""
        self.assertTrue(is_safe_redirect_url("admin:index"))

    def test_relative_path_is_safe(self):
        """Relative paths starting with / should be allowed."""
        self.assertTrue(is_safe_redirect_url("/dashboard"))
        self.assertTrue(is_safe_redirect_url("/"))
        self.assertTrue(is_safe_redirect_url("/path/to/page"))
        self.assertTrue(is_safe_redirect_url("/path?query=value"))
        self.assertTrue(is_safe_redirect_url("/path#anchor"))

    @patch("users.views.ALLOWED_REDIRECT_ORIGINS", ["http://localhost:3000", "https://example.com"])
    def test_allowed_origin_is_safe(self):
        """URLs with allowed origins should be accepted."""
        self.assertTrue(is_safe_redirect_url("http://localhost:3000/callback"))
        self.assertTrue(is_safe_redirect_url("http://localhost:3000"))
        self.assertTrue(is_safe_redirect_url("https://example.com/path"))
        self.assertTrue(is_safe_redirect_url("https://example.com"))

    @patch("users.views.ALLOW_PREVIEW_ENVIRONMENTS", True)
    @patch("users.views.PREVIEW_ORIGIN_REGEXES", [r"^https://[\w-]+-testownik\.b\.solvro\.pl$"])
    @patch("users.views.ALLOWED_REDIRECT_ORIGINS", ["http://localhost:3000"])
    def test_preview_environment_regex_is_safe(self):
        """Preview environment URLs matching regex should be allowed when enabled."""
        self.assertTrue(is_safe_redirect_url("https://pr-123-testownik.b.solvro.pl/callback"))
        self.assertTrue(is_safe_redirect_url("https://feature-branch-testownik.b.solvro.pl"))

    # --- INVALID CASES: Protocol-relative URLs ---

    def test_protocol_relative_url_is_blocked(self):
        """Protocol-relative URLs (//evil.com) must be blocked."""
        self.assertFalse(is_safe_redirect_url("//evil.com"))
        self.assertFalse(is_safe_redirect_url("//evil.com/path"))
        self.assertFalse(is_safe_redirect_url("//localhost:3000"))  # Even if it looks like allowed origin

    # --- INVALID CASES: Malicious URLs ---

    @patch("users.views.ALLOWED_REDIRECT_ORIGINS", ["http://localhost:3000"])
    def test_external_url_is_blocked(self):
        """External URLs not in allowed origins should be blocked."""
        self.assertFalse(is_safe_redirect_url("https://evil.com"))
        self.assertFalse(is_safe_redirect_url("https://evil.com/steal-tokens"))
        self.assertFalse(is_safe_redirect_url("http://attacker.com"))

    def test_javascript_url_is_blocked(self):
        """JavaScript URLs must be blocked."""
        self.assertFalse(is_safe_redirect_url("javascript:alert(1)"))
        self.assertFalse(is_safe_redirect_url("javascript:void(0)"))
        self.assertFalse(is_safe_redirect_url("JAVASCRIPT:alert(1)"))

    def test_data_url_is_blocked(self):
        """Data URLs must be blocked."""
        self.assertFalse(is_safe_redirect_url("data:text/html,<script>alert(1)</script>"))
        self.assertFalse(is_safe_redirect_url("data:,"))

    def test_file_url_is_blocked(self):
        """File URLs must be blocked."""
        self.assertFalse(is_safe_redirect_url("file:///etc/passwd"))
        self.assertFalse(is_safe_redirect_url("file://localhost/path"))

    def test_ftp_url_is_blocked(self):
        """FTP URLs must be blocked."""
        self.assertFalse(is_safe_redirect_url("ftp://evil.com/file"))

    # --- INVALID CASES: Edge cases and malformed URLs ---

    def test_empty_url_is_blocked(self):
        """Empty or None URLs should be blocked."""
        self.assertFalse(is_safe_redirect_url(""))
        self.assertFalse(is_safe_redirect_url(None))

    def test_whitespace_url_is_blocked(self):
        """Whitespace-only URLs should be blocked."""
        self.assertFalse(is_safe_redirect_url("   "))

    @patch("users.views.ALLOWED_REDIRECT_ORIGINS", ["http://localhost:3000"])
    def test_url_with_credentials_is_blocked(self):
        """URLs with embedded credentials should be blocked (not in allowed origins)."""
        self.assertFalse(is_safe_redirect_url("https://user:pass@evil.com"))
        self.assertFalse(is_safe_redirect_url("https://admin@evil.com"))

    @patch("users.views.ALLOWED_REDIRECT_ORIGINS", ["https://example.com"])
    def test_subdomain_attack_is_blocked(self):
        """Subdomain attacks should be blocked."""
        self.assertFalse(is_safe_redirect_url("https://example.com.evil.com"))
        self.assertFalse(is_safe_redirect_url("https://evilexample.com"))

    @patch("users.views.ALLOWED_REDIRECT_ORIGINS", ["https://example.com"])
    def test_port_variation_is_blocked(self):
        """Different ports on allowed origins should be blocked."""
        self.assertFalse(is_safe_redirect_url("https://example.com:8080"))
        self.assertFalse(is_safe_redirect_url("https://example.com:443/path"))  # Explicit port

    # --- INVALID CASES: URL manipulation attempts ---

    def test_backslash_url_is_blocked(self):
        """Backslash URLs that could be misinterpreted should be blocked."""
        self.assertFalse(is_safe_redirect_url("\\\\evil.com"))
        self.assertFalse(is_safe_redirect_url("\\/evil.com"))

    @patch("users.views.ALLOWED_REDIRECT_ORIGINS", ["http://localhost:3000"])
    def test_null_byte_injection_is_blocked(self):
        """URLs with null bytes should be handled safely."""
        self.assertFalse(is_safe_redirect_url("https://evil.com\x00.localhost:3000"))

    # --- Preview environments disabled ---

    @patch("users.views.ALLOW_PREVIEW_ENVIRONMENTS", False)
    @patch("users.views.PREVIEW_ORIGIN_REGEXES", [r"^https://[\w-]+-testownik\.b\.solvro\.pl$"])
    @patch("users.views.ALLOWED_REDIRECT_ORIGINS", ["http://localhost:3000"])
    def test_preview_url_blocked_when_disabled(self):
        """Preview environment URLs should be blocked when feature is disabled."""
        self.assertFalse(is_safe_redirect_url("https://pr-123-testownik.b.solvro.pl/callback"))

    # --- Scheme handling ---

    @patch("users.views.ALLOWED_REDIRECT_ORIGINS", ["http://localhost:3000"])
    def test_scheme_mismatch_is_blocked(self):
        """Wrong scheme on allowed origin should be blocked."""
        self.assertFalse(is_safe_redirect_url("https://localhost:3000"))  # https vs http

    def test_no_scheme_is_blocked(self):
        """URLs without scheme (not starting with /) should be blocked."""
        self.assertFalse(is_safe_redirect_url("evil.com"))
        self.assertFalse(is_safe_redirect_url("localhost:3000"))
