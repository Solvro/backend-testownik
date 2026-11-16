"""Login limits apply to bearer guests and use a separate guest-creation budget."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from mobile_api.models import LoginAttempt
from users.models import User
from users.serializers import UserTokenObtainPairSerializer


class MobileLoginThrottleBoundaryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.payload = {"provider": "usos", "challenge": "c" * 43, "state": "s" * 32}

    def tearDown(self):
        cache.clear()

    def assert_login_limit(self):
        for _ in range(10):
            self.assertEqual(self.client.post("/api/mobile/auth/start/", self.payload).status_code, 200)
        denied = self.client.post("/api/mobile/auth/start/", self.payload)
        self.assertEqual(denied.status_code, 429)
        self.assertEqual(LoginAttempt.objects.count(), 10)
        self.assertIn("Retry-After", denied)

    def test_anonymous_login_start_is_bounded(self):
        self.assert_login_limit()

    def test_guest_bearer_cannot_skip_login_start_limit(self):
        guest = User.objects.create_guest_user()
        token = UserTokenObtainPairSerializer.get_token(guest).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assert_login_limit()

    def test_registered_bearer_cannot_skip_login_start_limit(self):
        account = User.objects.create_user(email="login-throttle@example.invalid")
        token = UserTokenObtainPairSerializer.get_token(account).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assert_login_limit()

    def test_login_attempts_do_not_spend_new_guest_creation_budget(self):
        for _ in range(5):
            self.assertEqual(self.client.post("/api/mobile/auth/start/", self.payload).status_code, 200)
        guest = self.client.post("/api/mobile/auth/guest/", {}, format="json")
        self.assertEqual(guest.status_code, 201)

    def test_guest_creation_does_not_spend_login_start_budget(self):
        for _ in range(5):
            self.assertEqual(self.client.post("/api/mobile/auth/guest/", {}, format="json").status_code, 201)
        self.assert_login_limit()
        self.assertEqual(self.client.post("/api/mobile/auth/guest/", {}, format="json").status_code, 429)

    def test_login_traffic_cannot_erase_guest_hourly_limit_after_a_minute(self):
        with patch("rest_framework.throttling.SimpleRateThrottle.timer", return_value=1000):
            for _ in range(5):
                self.assertEqual(self.client.post("/api/mobile/auth/guest/", {}, format="json").status_code, 201)
        with patch("rest_framework.throttling.SimpleRateThrottle.timer", return_value=1061):
            self.assertEqual(self.client.post("/api/mobile/auth/start/", self.payload).status_code, 200)
            self.assertEqual(self.client.post("/api/mobile/auth/guest/", {}, format="json").status_code, 429)

    def test_same_ip_keeps_one_budget_across_anonymous_guest_and_account_tokens(self):
        for _ in range(9):
            self.assertEqual(self.client.post("/api/mobile/auth/start/", self.payload).status_code, 200)
        guest = User.objects.create_guest_user()
        guest_token = UserTokenObtainPairSerializer.get_token(guest).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {guest_token}")
        self.assertEqual(self.client.post("/api/mobile/auth/start/", self.payload).status_code, 200)
        account = User.objects.create_user(email="rotated-login-throttle@example.invalid")
        account_token = UserTokenObtainPairSerializer.get_token(account).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {account_token}")
        self.assertEqual(self.client.post("/api/mobile/auth/start/", self.payload).status_code, 429)
        self.client.credentials()
        self.assertEqual(self.client.post("/api/mobile/auth/start/", self.payload).status_code, 429)
        self.assertEqual(LoginAttempt.objects.count(), 10)
