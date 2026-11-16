import base64
import hashlib
import io
import tempfile
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone
from oauth2_provider.models import AccessToken, get_application_model
from PIL import Image
from rest_framework.test import APITestCase

from users.models import User


class MobileRestOAuthTests(APITestCase):
    def setUp(self):
        call_command("register_mobile_oauth", verbosity=0)
        self.application = get_application_model().objects.get(client_id="testownik-mobile")
        self.user = User.objects.create_user(email="native-oauth@example.invalid", password="test-password")
        self.verifier = "a" * 64

    def token(self, scope):
        token = AccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="opaque-" + str(timezone.now().timestamp()),
            scope=scope,
            expires=timezone.now() + timedelta(minutes=5),
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        return token

    def test_registration_rejects_existing_non_authorization_code_grant_without_changing_it(self):
        self.application.authorization_grant_type = self.application.GRANT_PASSWORD
        self.application.save(update_fields=["authorization_grant_type"])
        with self.assertRaises(CommandError):
            call_command("register_mobile_oauth", verbosity=0)
        self.application.refresh_from_db()
        self.assertEqual(self.application.authorization_grant_type, self.application.GRANT_PASSWORD)

    def test_matching_mobile_registration_is_idempotent(self):
        application_id = self.application.pk
        call_command("register_mobile_oauth", verbosity=0)
        self.application.refresh_from_db()
        self.assertEqual(self.application.pk, application_id)
        self.assertEqual(self.application.authorization_grant_type, self.application.GRANT_AUTHORIZATION_CODE)
        self.assertEqual(get_application_model().objects.filter(client_id="testownik-mobile").count(), 1)

    def test_mobile_can_organize_owned_library_with_write_scope(self):
        from quizzes.models import Folder, Quiz

        self.token("quizzes:read quizzes:write")
        response = self.client.post("/api/folders/", {"name": "Mobile destination"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        destination = response.data["id"]
        response = self.client.patch(f"/api/folders/{destination}/", {"name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        quiz = Quiz.objects.create(title="Organize test", creator=self.user, folder=self.user.root_folder)
        response = self.client.post(f"/api/quizzes/{quiz.id}/move/", {"folder_id": destination}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        quiz.refresh_from_db()
        self.assertEqual(str(quiz.folder_id), str(destination))
        child = Folder.objects.create(name="Child", owner=self.user, parent=self.user.root_folder)
        response = self.client.post(f"/api/folders/{child.id}/move/", {"parent_id": destination}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(f"/api/folders/{destination}/move/", {"parent_id": str(child.id)}, format="json")
        self.assertEqual(response.status_code, 400)
        self.token("quizzes:read")
        response = self.client.patch(f"/api/folders/{destination}/", {"name": "Denied"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_oauth_sharing_roles_and_revoke_use_existing_rest_endpoints(self):
        from quizzes.models import Quiz, SharedQuiz

        recipient = User.objects.create_user(email="sharing-recipient@example.invalid", password=None)
        quiz = Quiz.objects.create(title="Sharing OAuth fixture", creator=self.user, folder=self.user.root_folder)
        self.token("quizzes:read quizzes:write user:read")
        response = self.client.patch(
            f"/api/quizzes/{quiz.id}/", {"visibility": 1, "allow_anonymous": False, "is_anonymous": True}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["is_anonymous"])
        response = self.client.post(
            "/api/shared-quizzes/",
            {"quiz_id": str(quiz.id), "user_id": str(recipient.id), "allow_edit": False},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        share_id = response.data["id"]
        response = self.client.patch(f"/api/shared-quizzes/{share_id}/", {"allow_edit": True}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["allow_edit"])
        self.token("quizzes:read")
        self.assertEqual(self.client.delete(f"/api/shared-quizzes/{share_id}/").status_code, 403)
        self.assertTrue(SharedQuiz.objects.filter(pk=share_id).exists())
        self.token("quizzes:read quizzes:write")
        self.assertEqual(self.client.delete(f"/api/shared-quizzes/{share_id}/").status_code, 204)
        self.assertFalse(SharedQuiz.objects.filter(pk=share_id).exists())

    def test_oauth_notification_read_state_is_scoped_to_the_account(self):
        from notifications.models import Notification

        other = User.objects.create_user(email="other-inbox@example.invalid", password=None)
        mine = Notification.objects.create(
            user=self.user, title="My update", content="Fixture", notification_type="in_app"
        )
        theirs = Notification.objects.create(
            user=other, title="Other update", content="Fixture", notification_type="in_app"
        )
        self.token("notifications:read")
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([str(item["id"]) for item in response.data], [str(mine.id)])
        self.assertEqual(
            self.client.patch(f"/api/notifications/{mine.id}/", {"is_read": True}, format="json").status_code, 403
        )
        self.token("notifications:read notifications:write")
        self.assertEqual(
            self.client.patch(f"/api/notifications/{theirs.id}/", {"is_read": True}, format="json").status_code, 404
        )
        self.assertEqual(
            self.client.patch(f"/api/notifications/{mine.id}/", {"is_read": True}, format="json").status_code, 200
        )
        mine.refresh_from_db()
        self.assertTrue(mine.is_read)
        self.assertEqual(
            self.client.patch(f"/api/notifications/{mine.id}/", {"is_read": False}, format="json").status_code, 200
        )
        self.assertEqual(self.client.patch("/api/notifications/mark-all-read/", {}, format="json").status_code, 200)
        mine.refresh_from_db()
        theirs.refresh_from_db()
        self.assertTrue(mine.is_read)
        self.assertFalse(theirs.is_read)

    def code(self):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip("=")
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/oauth/authorize/request/",
            {
                "authorization_params": {
                    "client_id": "testownik-mobile",
                    "redirect_uri": "testownik://auth",
                    "response_type": "code",
                    "scope": "user:read quizzes:read",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "state": "native-test-state",
                },
                "scopes": ["user:read", "quizzes:read"],
                "allow": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.client.force_authenticate(None)
        query = parse_qs(urlparse(response.data["redirect_url"]).query)
        self.assertEqual(query["state"], ["native-test-state"])
        return query["code"][0]

    def exchange(self, code, verifier):
        return self.client.post(
            "/api/oauth/token/",
            {
                "client_id": "testownik-mobile",
                "redirect_uri": "testownik://auth",
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            },
        )

    def test_authorization_code_refresh_and_revoke(self):
        code = self.code()
        response = self.exchange(code, self.verifier)
        self.assertEqual(response.status_code, 200, response.content)
        tokens = response.json()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
        self.assertEqual(self.client.get("/api/user/").status_code, 200)
        self.assertEqual(self.client.get("/api/library/").status_code, 200)
        self.client.credentials()
        self.assertEqual(self.exchange(code, self.verifier).status_code, 400)
        refreshed = self.client.post(
            "/api/oauth/token/",
            {"client_id": "testownik-mobile", "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        self.assertNotEqual(refreshed.json()["refresh_token"], tokens["refresh_token"])
        revoked = self.client.post(
            "/api/oauth/revoke_token/",
            {
                "client_id": "testownik-mobile",
                "token": refreshed.json()["refresh_token"],
                "token_type_hint": "refresh_token",
            },
        )
        self.assertEqual(revoked.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refreshed.json()['access_token']}")
        self.assertEqual(self.client.get("/api/user/").status_code, 401)

    def test_wrong_pkce_verifier_is_rejected(self):
        self.assertEqual(self.exchange(self.code(), "b" * 64).status_code, 400)

    def test_read_scope_cannot_write_or_read_grades(self):
        self.token("user:read quizzes:read")
        self.assertEqual(
            self.client.patch("/api/settings/", {"initial_reoccurrences": 2}, format="json").status_code, 403
        )
        self.assertEqual(self.client.post("/api/folders/", {"name": "unauthorized"}, format="json").status_code, 403)
        self.assertEqual(self.client.get("/api/grades/").status_code, 403)
        self.assertEqual(self.client.post("/api/user/delete-account/", {}, format="json").status_code, 403)
        self.assertEqual(self.client.get("/api/oauth/identity/").status_code, 403)

    def test_write_scope_preserves_existing_settings_behavior(self):
        self.token("user:write")
        response = self.client.patch("/api/settings/", {"initial_reoccurrences": 2}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["initial_reoccurrences"], 2)

    def test_expired_and_banned_tokens_are_rejected(self):
        token = self.token("user:read")
        token.expires = timezone.now() - timedelta(seconds=1)
        token.save()
        self.assertEqual(self.client.get("/api/user/").status_code, 401)
        self.token("user:read")
        self.user.is_banned = True
        self.user.save()
        self.assertEqual(self.client.get("/api/user/").status_code, 401)

    def test_ai_identity_requires_ai_write(self):
        self.token("ai:write")
        response = self.client.get("/api/oauth/identity/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user_id"], str(self.user.pk))
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_embedded_session_cannot_escalate_oauth_scope(self):
        self.token("web:read")
        self.assertEqual(self.client.post("/api/mobile/auth/web-session/").status_code, 403)
        self.token("web:read study:read quizzes:read user:read")
        response = self.client.post("/api/mobile/auth/web-session/")
        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(self.client.get("/api/library/").status_code, 200)
        self.assertEqual(
            self.client.patch("/api/settings/", {"initial_reoccurrences": 3}, format="json").status_code, 403
        )
        self.assertEqual(self.client.get("/api/oauth/identity/").status_code, 403)

    def test_oauth_profile_photo_upload_and_remove(self):
        image = io.BytesIO()
        Image.new("RGB", (32, 32), "blue").save(image, format="PNG")

        def photo():
            return SimpleUploadedFile("avatar.png", image.getvalue(), content_type="image/png")

        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.token("user:read")
            self.assertEqual(
                self.client.post("/api/user/photo/", {"photo": photo()}, format="multipart").status_code, 403
            )
            self.token("user:read user:write")
            response = self.client.post("/api/user/photo/", {"photo": photo()}, format="multipart")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertTrue(response.data["has_custom_photo"])
            self.assertTrue(response.data["photo"])
            self.user.refresh_from_db()
            self.assertIsNotNone(self.user.custom_photo_image_id)
            response = self.client.delete("/api/user/photo/")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertFalse(response.data["has_custom_photo"])

    def test_oauth_quiz_image_upload_attach_and_remove(self):
        from quizzes.models import Answer, Question, Quiz

        image = io.BytesIO()
        Image.new("RGB", (32, 24), "blue").save(image, format="PNG")

        def photo():
            return SimpleUploadedFile("question.png", image.getvalue(), content_type="image/png")

        quiz = Quiz.objects.create(title="Image edit", creator=self.user, folder=self.user.root_folder)
        question = Question.objects.create(quiz=quiz, text="Question", order=1)
        answer = Answer.objects.create(question=question, text="Answer", order=1, is_correct=True)
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.token("quizzes:read")
            self.assertEqual(self.client.post("/api/upload/", {"image": photo()}, format="multipart").status_code, 403)
            self.token("quizzes:read quizzes:write")
            upload = self.client.post("/api/upload/", {"image": photo()}, format="multipart")
            self.assertEqual(upload.status_code, 201, upload.data)
            self.assertTrue(upload.data["url"])
            self.assertEqual((upload.data["width"], upload.data["height"]), (32, 24))
            payload = {
                "questions": [
                    {
                        "id": str(question.id),
                        "text": "Question",
                        "order": 1,
                        "multiple": False,
                        "image_upload": upload.data["id"],
                        "image_url": None,
                        "answers": [
                            {
                                "id": str(answer.id),
                                "text": "Answer",
                                "order": 1,
                                "is_correct": True,
                                "image_upload": upload.data["id"],
                                "image_url": None,
                            }
                        ],
                    }
                ]
            }
            response = self.client.patch(f"/api/quizzes/{quiz.id}/", payload, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            question.refresh_from_db()
            answer.refresh_from_db()
            self.assertEqual(str(question.image_upload_id), str(upload.data["id"]))
            self.assertEqual(str(answer.image_upload_id), str(upload.data["id"]))
            payload["questions"][0]["image_upload"] = None
            payload["questions"][0]["answers"][0]["image_upload"] = None
            response = self.client.patch(f"/api/quizzes/{quiz.id}/", payload, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            question.refresh_from_db()
            answer.refresh_from_db()
            self.assertIsNone(question.image_upload_id)
            self.assertIsNone(answer.image_upload_id)
