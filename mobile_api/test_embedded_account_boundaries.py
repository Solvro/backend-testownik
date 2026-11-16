"""An embedded read session must never authorize guest account migration."""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

from django.test import TestCase
from rest_framework.test import APIClient

from mobile_api.models import LoginAttempt
from quizzes.models import Quiz
from users.models import User
from users.serializers import UserTokenObtainPairSerializer


class EmbeddedAccountBoundaryTests(TestCase):
    def setUp(self):
        self.guest = User.objects.create_guest_user()
        self.account = User.objects.create_user(email="embedded-boundary-account@example.invalid")
        self.quiz = Quiz.objects.create(
            title="Embedded guest fixture", creator=self.guest, folder=self.guest.root_folder
        )
        self.client = APIClient()
        self.verifier = "v" * 64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip("=")
        self.start = {"provider": "usos", "challenge": challenge, "state": "s" * 32}

    def guest_token(self):
        access = UserTokenObtainPairSerializer.get_token(self.guest).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    def embedded_token(self):
        self.guest_token()
        response = self.client.post("/api/mobile/auth/web-session/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

    def test_embedded_guest_token_cannot_bind_guest_to_login_attempt(self):
        self.embedded_token()
        response = self.client.post("/api/mobile/auth/start/", self.start, format="json")
        self.assertEqual(
            response.status_code, 403, f"bound_guest_attempts={LoginAttempt.objects.filter(guest=self.guest).count()}"
        )
        self.assertFalse(LoginAttempt.objects.exists())
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator_id, self.guest.pk)

    def test_embedded_guest_token_cannot_transfer_data_after_other_account_login(self):
        self.embedded_token()
        started = self.client.post("/api/mobile/auth/start/", self.start, format="json")
        if started.status_code == 200:
            # Complete the attack only inside this disposable database to prove
            # the effect of accepting the restricted token as migration proof.
            attempt = LoginAttempt.objects.get()
            self.client.credentials()
            self.client.get(f"/api/mobile/auth/browser/{attempt.pk}/")
            self.client.force_login(self.account)
            completed = self.client.get("/api/mobile/auth/complete/")
            self.assertEqual(completed.status_code, 302)
            values = {key: value[0] for key, value in parse_qs(urlparse(completed["Location"]).query).items()}
            exchanged = self.client.post(
                "/api/mobile/auth/exchange/",
                {"attempt": values["attempt"], "code": values["code"], "verifier": self.verifier},
                format="json",
            )
            self.assertEqual(exchanged.status_code, 200)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator_id, self.guest.pk, "Embedded read token migrated the guest quiz")
        self.assertTrue(User.objects.filter(pk=self.guest.pk).exists())
        self.assertEqual(started.status_code, 403)

    def test_ordinary_guest_bearer_still_binds_migration_attempt(self):
        self.guest_token()
        response = self.client.post("/api/mobile/auth/start/", self.start, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LoginAttempt.objects.get().guest_id, self.guest.pk)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator_id, self.guest.pk)

    def test_anonymous_login_start_remains_available_without_guest_binding(self):
        self.assertEqual(self.client.post("/api/mobile/auth/start/", self.start, format="json").status_code, 200)
        self.assertIsNone(LoginAttempt.objects.get().guest_id)
