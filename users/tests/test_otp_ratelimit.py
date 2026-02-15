"""
Tests for rate limiting on OTP generation and login endpoints.
"""

from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from users.models import User


class GenerateOtpRateLimitTestCase(APITestCase):
    """Tests for rate limiting on the generate-otp endpoint."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
            password="testpassword123",
        )
        self.url = reverse("generate_otp")

    def test_requests_within_limit_succeed(self):
        """Test that requests within the rate limit succeed."""
        for i in range(3):
            response = self.client.post(
                self.url,
                {"email": f"user{i}@example.com"},
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_200_OK,
                f"Request {i + 1} should succeed within IP rate limit",
            )

    def test_ip_rate_limit_blocks_after_limit(self):
        """Test that IP-based rate limiting blocks after 3 requests/minute."""
        for i in range(3):
            response = self.client.post(
                self.url,
                {"email": f"user{i}@example.com"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 4th request should be blocked
        response = self.client.post(
            self.url,
            {"email": "another@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class LoginOtpRateLimitTestCase(APITestCase):
    """Tests for rate limiting on the login-otp endpoint."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
            password="testpassword123",
        )
        self.url = reverse("login_otp")

    def test_requests_within_limit_succeed(self):
        """Test that requests within the rate limit succeed (even with wrong OTP)."""
        for i in range(10):
            response = self.client.post(
                self.url,
                {"email": "test@example.com", "otp": "000000"},
                format="json",
            )
            # Should get 400 (invalid OTP), not 403 (rate limited)
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
                f"Request {i + 1} should not be rate limited",
            )

    def test_ip_rate_limit_blocks_after_limit(self):
        """Test that IP-based rate limiting blocks after 10 requests/minute."""
        for i in range(10):
            response = self.client.post(
                self.url,
                {"email": "test@example.com", "otp": "000000"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # 11th request should be blocked by rate limit
        response = self.client.post(
            self.url,
            {"email": "test@example.com", "otp": "000000"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
