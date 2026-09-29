import base64
import hashlib
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from quizzes.models import Answer, AnswerRecord, Question, Quiz, QuizSession, SharedQuiz
from users.models import EmailLoginToken, User
from users.serializers import UserTokenObtainPairSerializer

from .models import LoginAttempt


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MobileTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(email="mobile@example.invalid", password="test-only-password")

    def authenticate(self):
        token = UserTokenObtainPairSerializer.get_token(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        return token

    def test_guest_tokens_and_private_profile(self):
        response = self.client.post("/api/mobile/auth/guest/", {}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.cookies), 0)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(self.client.get("/api/user/").status_code, 200)

    def test_refresh_and_logout(self):
        token = self.authenticate()
        response = self.client.post("/api/mobile/auth/refresh/", {"refresh": str(token)}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        refreshed = response.data["refresh"]
        self.assertEqual(
            self.client.post("/api/mobile/auth/logout/", {"refresh": refreshed}, format="json").status_code, 204
        )
        self.assertEqual(
            self.client.post("/api/mobile/auth/refresh/", {"refresh": refreshed}, format="json").status_code, 401
        )

    def test_embedded_web_session_is_short_lived_and_does_not_rotate_mobile_tokens(self):
        from rest_framework_simplejwt.tokens import AccessToken

        self.assertEqual(self.client.post("/api/mobile/auth/web-session/").status_code, 401)
        mobile = self.authenticate()
        response = self.client.post("/api/mobile/auth/web-session/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("refresh", response.data)
        token = AccessToken(response.data["access"])
        self.assertTrue(token["mobile_embed"])
        self.assertLessEqual(token["exp"] - token["iat"], 1800)
        self.assertEqual(str(token["user_id"]), str(self.user.pk))
        self.assertEqual(
            self.client.post("/api/mobile/auth/refresh/", {"refresh": str(mobile)}, format="json").status_code, 200
        )

    def test_otp_preserves_cookie_web_contract(self):
        token = EmailLoginToken.create_for_user(self.user)
        response = self.client.post(
            "/api/mobile/auth/otp/", {"email": self.user.email, "otp": token.otp_code}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertEqual(len(response.cookies), 0)
        token = EmailLoginToken.create_for_user(self.user)
        response = self.client.post("/api/login-otp/", {"email": self.user.email, "otp": token.otp_code}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access", response.data)
        self.assertIn("access_token", response.cookies)

    def test_pkce_exchange_rejects_wrong_verifier_and_replay(self):
        verifier = "v" * 64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        started = self.client.post(
            "/api/mobile/auth/start/", {"provider": "usos", "challenge": challenge, "state": "s" * 32}, format="json"
        )
        self.assertEqual(started.status_code, 200)
        attempt = LoginAttempt.objects.get()
        self.client.get(f"/api/mobile/auth/browser/{attempt.pk}/")
        self.client.force_login(self.user)
        completed = self.client.get("/api/mobile/auth/complete/")
        self.assertEqual(completed.status_code, 302)
        query = {k: v[0] for k, v in parse_qs(urlparse(completed["Location"]).query).items()}
        self.assertNotIn("access", query)
        payload = {"attempt": query["attempt"], "code": query["code"], "verifier": "x" * 64}
        self.assertEqual(self.client.post("/api/mobile/auth/exchange/", payload, format="json").status_code, 400)
        payload["verifier"] = verifier
        response = self.client.post("/api/mobile/auth/exchange/", payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post("/api/mobile/auth/exchange/", payload, format="json").status_code, 400)

    def test_browser_callback_requires_bound_session(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/api/mobile/auth/complete/").status_code, 400)

    def test_guest_upgrade_requires_bearer_ownership_and_pkce(self):
        guest = User.objects.create_guest_user()
        quiz = Quiz.objects.create(title="Guest work", creator=guest, folder=guest.root_folder)
        verifier = "v" * 64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        start = {"provider": "usos", "challenge": challenge, "state": "s" * 32}
        self.assertEqual(
            self.client.post("/api/mobile/auth/start/", {**start, "guest_id": str(guest.pk)}).status_code, 400
        )
        guest_token = UserTokenObtainPairSerializer.get_token(guest)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {guest_token.access_token}")
        self.assertEqual(self.client.post("/api/mobile/auth/start/", start).status_code, 200)
        attempt = LoginAttempt.objects.get()
        self.assertEqual(attempt.guest_id, guest.pk)
        self.client.credentials()
        self.client.get(f"/api/mobile/auth/browser/{attempt.pk}/")
        self.client.force_login(self.user)
        completed = self.client.get("/api/mobile/auth/complete/")
        query = {k: v[0] for k, v in parse_qs(urlparse(completed["Location"]).query).items()}
        payload = {"attempt": query["attempt"], "code": query["code"], "verifier": "x" * 64}
        self.assertEqual(self.client.post("/api/mobile/auth/exchange/", payload).status_code, 400)
        quiz.refresh_from_db()
        self.assertEqual(quiz.creator_id, guest.pk)
        payload["verifier"] = verifier
        with patch("mobile_api.views.migrate_guest_to_user", return_value=False):
            self.assertEqual(self.client.post("/api/mobile/auth/exchange/", payload).status_code, 409)
        attempt.refresh_from_db()
        self.assertFalse(attempt.consumed)
        self.assertEqual(self.client.post("/api/mobile/auth/exchange/", payload).status_code, 200)
        quiz.refresh_from_db()
        self.assertEqual(quiz.creator_id, self.user.pk)
        self.assertEqual(quiz.folder_id, self.user.root_folder_id)
        self.assertFalse(User.objects.filter(pk=guest.pk).exists())
        self.assertEqual(self.client.post("/api/mobile/auth/exchange/", payload).status_code, 400)

    def test_normal_account_is_never_bound_for_migration(self):
        self.authenticate()
        response = self.client.post(
            "/api/mobile/auth/start/", {"provider": "usos", "challenge": "c" * 43, "state": "s" * 32}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(LoginAttempt.objects.get().guest_id)

    def quiz_payload(self):
        self.authenticate()
        quiz = Quiz.objects.create(title="Mobile test", creator=self.user, folder=self.user.root_folder, visibility=0)
        question = Question.objects.create(quiz=quiz, text="2 + 2?", order=0)
        answer = Answer.objects.create(question=question, text="4", is_correct=True, order=0)
        session, _ = QuizSession.get_or_create_active(quiz, self.user)
        return (
            quiz,
            session,
            {
                "request_id": str(uuid.uuid4()),
                "session_id": str(session.pk),
                "version": quiz.version,
                "question_id": str(question.pk),
                "selected_answers": [str(answer.pk)],
                "elapsed_seconds": 12,
                "next_question": None,
            },
        )

    def test_offline_answer_retry_is_idempotent(self):
        quiz, session, payload = self.quiz_payload()
        url = f"/api/mobile/quizzes/{quiz.pk}/answer/"
        first = self.client.post(url, payload, format="json")
        second = self.client.post(url, payload, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(AnswerRecord.objects.count(), 1)
        session.refresh_from_db()
        self.assertEqual(session.study_time.total_seconds(), 12)
        payload["selected_answers"] = []
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 409)

    def test_stale_session_and_version_are_not_applied(self):
        quiz, session, payload = self.quiz_payload()
        payload["version"] += 1
        self.assertEqual(
            self.client.post(f"/api/mobile/quizzes/{quiz.pk}/answer/", payload, format="json").status_code, 409
        )
        payload["version"] = quiz.version
        session.is_active = False
        session.save()
        self.assertEqual(
            self.client.post(f"/api/mobile/quizzes/{quiz.pk}/answer/", payload, format="json").status_code, 409
        )
        self.assertEqual(AnswerRecord.objects.count(), 0)

    def test_invalid_next_question_rolls_back_answer(self):
        quiz, session, payload = self.quiz_payload()
        payload["next_question"] = str(uuid.uuid4())
        self.assertEqual(
            self.client.post(f"/api/mobile/quizzes/{quiz.pk}/answer/", payload, format="json").status_code, 400
        )
        self.assertEqual(AnswerRecord.objects.count(), 0)

    def test_other_user_cannot_submit_to_private_quiz(self):
        quiz, session, payload = self.quiz_payload()
        other = User.objects.create_user(email="other@example.invalid")
        self.client.force_authenticate(other)
        self.assertEqual(
            self.client.post(f"/api/mobile/quizzes/{quiz.pk}/answer/", payload, format="json").status_code, 403
        )


class MobileAccountDeletionTests(TestCase):
    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone
        from oauth2_provider.models import AbstractApplication, AccessToken, Application

        self.client = APIClient()
        self.user = User.objects.create_user(email="leaving@example.invalid", first_name="Ada", last_name="Leaving")
        self.heir = User.objects.create_user(email="heir@example.invalid", first_name="Ola", last_name="Heir")
        self.learner = User.objects.create_user(email="learner@example.invalid")
        self.quiz = Quiz.objects.create(title="Owned", creator=self.user, folder=self.user.root_folder, visibility=3)
        SharedQuiz.objects.create(quiz=self.quiz, user=self.learner)
        QuizSession.objects.create(quiz=self.quiz, user=self.learner)
        QuizSession.objects.create(quiz=self.quiz, user=self.user)

        def grant(client_id):
            application = Application.objects.create(
                name=client_id,
                client_id=client_id,
                client_type=AbstractApplication.CLIENT_PUBLIC,
                authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="testownik://auth",
            )
            return AccessToken.objects.create(
                user=self.user,
                application=application,
                token=f"token-{client_id}",
                expires=timezone.now() + timedelta(minutes=30),
                scope="user:read user:write",
            ).token

        self.mobile_token = grant("testownik-mobile")
        self.other_token = grant("third-party")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.mobile_token}")

    def test_preview_explains_who_loses_access(self):
        response = self.client.get("/api/mobile/account/deletion/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["quizzes"], 1)
        self.assertEqual(response.data["public_quizzes"], 1)
        self.assertEqual(response.data["shared_people"], 1)
        self.assertEqual(response.data["recent_learners"], 1)
        self.assertEqual(response.data["sessions"], 1)

    def test_third_party_apps_cannot_delete_accounts(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.other_token}")
        self.assertEqual(self.client.post("/api/mobile/account/deletion/", {}, format="json").status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_and_transfer_quizzes(self):
        response = self.client.post(
            "/api/mobile/account/deletion/", {"transfer_to_user_id": str(self.heir.pk)}, format="json"
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator, self.heir)
        self.assertEqual(self.quiz.folder, self.heir.root_folder)
        self.assertTrue(QuizSession.objects.filter(quiz=self.quiz, user=self.learner).exists())
        self.assertTrue(self.heir.notifications.filter(title="Otrzymano quizy").exists())

    def test_rejects_invalid_transfer_targets_and_keeps_the_account(self):
        guest = User.objects.create_user(email="guest@example.invalid", account_type="guest")
        for target in (self.user.pk, guest.pk, uuid.uuid4()):
            response = self.client.post(
                "/api/mobile/account/deletion/", {"transfer_to_user_id": str(target)}, format="json"
            )
            self.assertEqual(response.status_code, 400, target)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_without_transfer_removes_quizzes(self):
        self.assertEqual(self.client.post("/api/mobile/account/deletion/", {}, format="json").status_code, 204)
        self.assertFalse(Quiz.objects.filter(pk=self.quiz.pk).exists())


class WebAccountDeletionTests(TestCase):
    def test_account_with_quizzes_and_foreign_quizzes_in_its_folders_can_be_deleted(self):
        from quizzes.models import Folder

        client = APIClient()
        user = User.objects.create_user(email="web-leaving@example.invalid")
        other = User.objects.create_user(email="web-other@example.invalid")
        Quiz.objects.create(title="Mine", creator=user, folder=user.root_folder)
        subfolder = Folder.objects.create(name="Shared", owner=user, parent=user.root_folder)
        foreign = Quiz.objects.create(title="Theirs", creator=other, folder=subfolder)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {UserTokenObtainPairSerializer.get_token(user).access_token}")

        self.assertEqual(client.post("/api/user/delete-account/", {}, format="json").status_code, 200)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        foreign.refresh_from_db()
        self.assertEqual(foreign.folder, other.root_folder)

    def test_cannot_transfer_to_self(self):
        client = APIClient()
        user = User.objects.create_user(email="web-self@example.invalid")
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {UserTokenObtainPairSerializer.get_token(user).access_token}")
        response = client.post("/api/user/delete-account/", {"transfer_to_user_id": str(user.pk)}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
