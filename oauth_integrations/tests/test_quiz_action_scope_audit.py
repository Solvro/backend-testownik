"""Action overrides must retain OAuth scope and unavailable-account checks."""

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from oauth2_provider.models import AccessToken, get_application_model
from rest_framework.test import APIClient

from quizzes.models import Folder, FolderType, Question, Quiz, QuizSession
from users.models import User


class QuizActionScopeAuditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="action-scope-owner@example.invalid")
        application = get_application_model()
        self.application = application.objects.create(
            user=self.user,
            client_id="action-scope-third-party-fixture",
            name="Disposable scope fixture",
            client_type=application.CLIENT_PUBLIC,
            authorization_grant_type=application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.invalid/callback",
        )
        self.quiz = Quiz.objects.create(title="Scope fixture", creator=self.user, folder=self.user.root_folder)
        self.question = Question.objects.create(quiz=self.quiz, text="Scope fixture question", order=0)
        self.session = QuizSession.objects.create(quiz=self.quiz, user=self.user, current_question=self.question)
        self.destination = Folder.objects.create(
            name="Scope destination", owner=self.user, parent=self.user.root_folder
        )
        self.client = APIClient()
        self.url = f"/api/quizzes/{self.quiz.id}/"

    def token(self, scope):
        token = AccessToken.objects.create(
            user=self.user,
            application=self.application,
            token="action-scope-fixture-" + str(uuid.uuid4()),
            scope=scope,
            expires=timezone.now() + timedelta(minutes=5),
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

    def test_unrelated_scope_cannot_read_progress_or_statistics(self):
        self.token("feedback:write")
        for action in (
            "progress",
            "stats",
            "stats/timeline",
            "stats/sessions",
            "stats/hardest-questions",
            "stats/hourly",
        ):
            with self.subTest(action=action):
                self.assertEqual(self.client.get(f"{self.url}{action}/").status_code, 403)

    def test_unrelated_scope_cannot_reset_progress(self):
        self.token("feedback:write")
        response = self.client.delete(f"{self.url}progress/")
        self.session.refresh_from_db()
        self.assertEqual(response.status_code, 403, f"original_session_active={self.session.is_active}")
        self.assertTrue(self.session.is_active)
        self.assertEqual(QuizSession.objects.filter(quiz=self.quiz, user=self.user).count(), 1)

    def test_unrelated_scope_cannot_move_quiz(self):
        self.token("feedback:write")
        response = self.client.post(f"{self.url}move/", {"folder_id": str(self.destination.id)}, format="json")
        self.quiz.refresh_from_db()
        self.assertEqual(response.status_code, 403, f"moved={self.quiz.folder_id == self.destination.id}")
        self.assertEqual(self.quiz.folder_id, self.user.root_folder_id)

    def test_unrelated_scope_cannot_archive_quiz(self):
        self.token("feedback:write")
        response = self.client.post(f"{self.url}move-to-archive/", {}, format="json")
        self.quiz.refresh_from_db()
        self.assertEqual(response.status_code, 403, f"archived={self.quiz.folder.folder_type == FolderType.ARCHIVE}")
        self.assertEqual(self.quiz.folder_id, self.user.root_folder_id)

    def test_unrelated_scope_cannot_restore_deleted_quiz(self):
        trash, _ = Folder.objects.get_or_create(
            owner=self.user,
            folder_type=FolderType.TRASH,
            defaults={"name": "Scope trash", "parent": self.user.root_folder},
        )
        self.quiz.folder = trash
        self.quiz.deleted_at = timezone.now()
        self.quiz.save(update_fields=["folder", "deleted_at"])
        self.token("feedback:write")
        response = self.client.post(f"{self.url}restore/", {}, format="json")
        self.quiz.refresh_from_db()
        self.assertEqual(response.status_code, 403, f"restored={self.quiz.folder_id == self.user.root_folder_id}")
        self.assertEqual(self.quiz.folder_id, trash.id)
        self.token("quizzes:write")
        self.assertEqual(self.client.post(f"{self.url}restore/", {}, format="json").status_code, 200)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.folder_id, self.user.root_folder_id)
        self.assertIsNone(self.quiz.deleted_at)

    def test_valid_study_scopes_allow_progress_and_statistics(self):
        self.token("study:read study:write")
        self.assertEqual(self.client.get(f"{self.url}progress/").status_code, 200)
        self.assertEqual(self.client.get(f"{self.url}stats/").status_code, 200)
        self.assertEqual(self.client.delete(f"{self.url}progress/").status_code, 200)
        self.session.refresh_from_db()
        self.assertFalse(self.session.is_active)

    def test_valid_quiz_write_scope_allows_move_and_archive(self):
        self.token("quizzes:write")
        self.assertEqual(
            self.client.post(f"{self.url}move/", {"folder_id": str(self.destination.id)}, format="json").status_code,
            200,
        )
        self.assertEqual(self.client.post(f"{self.url}move-to-archive/", {}, format="json").status_code, 200)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.folder.folder_type, FolderType.ARCHIVE)

    def test_unrelated_scope_still_cannot_read_main_quiz_endpoint(self):
        self.token("feedback:write")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_study_read_scope_cannot_reset_progress(self):
        self.token("study:read")
        self.assertEqual(self.client.delete(f"{self.url}progress/").status_code, 403)
        self.session.refresh_from_db()
        self.assertTrue(self.session.is_active)

    def test_quiz_read_scope_cannot_archive(self):
        self.token("quizzes:read")
        self.assertEqual(self.client.post(f"{self.url}move-to-archive/", {}, format="json").status_code, 403)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.folder_id, self.user.root_folder_id)

    def test_quiz_write_scope_does_not_include_study_read(self):
        self.token("quizzes:write")
        self.assertEqual(self.client.get(f"{self.url}stats/").status_code, 403)

    def test_first_party_jwt_still_reads_and_resets_own_progress(self):
        from users.serializers import UserTokenObtainPairSerializer

        access = UserTokenObtainPairSerializer.get_token(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(self.client.get(f"{self.url}progress/").status_code, 200)
        self.assertEqual(self.client.delete(f"{self.url}progress/").status_code, 200)

    def test_banned_oauth_user_cannot_read_actions(self):
        self.user.is_banned = True
        self.user.save(update_fields=["is_banned"])
        self.token("study:read quizzes:read")
        self.assertEqual(self.client.get(f"{self.url}progress/").status_code, 401)

    def test_copy_requires_quiz_write_scope(self):
        before = Quiz.objects.count()
        self.token("feedback:write")
        self.assertEqual(self.client.post(f"{self.url}copy/", {}, format="json").status_code, 403)
        self.assertEqual(Quiz.objects.count(), before)
        self.token("quizzes:write")
        self.assertEqual(self.client.post(f"{self.url}copy/", {}, format="json").status_code, 201)
        self.assertEqual(Quiz.objects.count(), before + 1)

    def test_answer_requires_study_write_scope(self):
        body = {"question_id": str(self.question.id), "selected_answers": []}
        self.token("quizzes:write")
        self.assertEqual(self.client.post(f"{self.url}answer/", body, format="json").status_code, 403)
        self.assertEqual(self.session.answers.count(), 0)
        self.token("study:write")
        self.assertEqual(self.client.post(f"{self.url}answer/", body, format="json").status_code, 201)
        self.assertEqual(self.session.answers.count(), 1)

    def test_head_statistics_uses_study_read_scope(self):
        self.token("feedback:write")
        self.assertEqual(self.client.head(f"{self.url}stats/").status_code, 403)
        self.token("study:read")
        self.assertEqual(self.client.head(f"{self.url}stats/").status_code, 200)

    def test_embedded_jwt_reads_statistics_but_cannot_reset_progress(self):
        from users.serializers import UserTokenObtainPairSerializer

        access = UserTokenObtainPairSerializer.get_token(self.user).access_token
        access["mobile_embed"] = True
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(self.client.get(f"{self.url}stats/").status_code, 200)
        self.assertEqual(self.client.delete(f"{self.url}progress/").status_code, 403)
        self.session.refresh_from_db()
        self.assertTrue(self.session.is_active)
