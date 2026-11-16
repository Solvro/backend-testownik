"""Report validation and access regressions. All outbound notifications are mocked."""

import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from oauth2_provider.models import AccessToken, get_application_model
from rest_framework.test import APIClient

from quizzes.models import Folder, FolderType, Question, Quiz, SharedQuiz
from users.models import StudyGroup, User


class ReportQuestionRecoveryTests(TestCase):
    url = "/api/report-question-issue/"

    def setUp(self):
        self.author = User.objects.create_user(email="report-author@example.invalid")
        self.reader = User.objects.create_user(email="report-reader@example.invalid")
        self.quiz = Quiz.objects.create(
            title="Report fixture", creator=self.author, folder=self.author.root_folder, visibility=2
        )
        self.question = Question.objects.create(quiz=self.quiz, text="Fixture question", order=1)
        self.data = {"quiz_id": str(self.quiz.id), "question_id": str(self.question.id), "issue": "Synthetic issue"}
        self.client = APIClient()
        self.client.force_authenticate(user=self.reader)
        self.client.raise_request_exception = False
        self.notification = patch("quizzes.views.send_notification").start()
        self.addCleanup(patch.stopall)

    def post(self, changes=None):
        return self.client.post(self.url, json.dumps({**self.data, **(changes or {})}), content_type="application/json")

    def assert_denied(self, changes, status):
        response = self.post(changes)
        self.assertEqual(response.status_code, status, response.data)
        self.notification.assert_not_called()
        return response

    def test_missing_or_malformed_identifiers_are400(self):
        for field in ("quiz_id", "question_id"):
            for invalid in (None, "", "not-a-uuid", [], [str(uuid.uuid4())], {}):
                with self.subTest(field=field, value=invalid):
                    response = self.assert_denied({field: invalid}, 400)
                    self.assertIsInstance(response.data["error"], str)
                    self.assertIn(field, response.data["errors"])
            missing = {key: value for key, value in self.data.items() if key != field}
            response = self.client.post(self.url, missing, format="json")
            self.assertEqual(response.status_code, 400)
            self.notification.assert_not_called()

    def test_numeric_uuid_input_remains_recoverable404(self):
        for field in ("quiz_id", "question_id"):
            with self.subTest(field=field):
                self.assert_denied({field: 42}, 404)

    def test_invalid_issue_never_sends(self):
        for invalid in (None, "", " \n\t ", {}, [], True, "\x00", "\ud800"):
            with self.subTest(issue=repr(invalid)):
                self.assert_denied({"issue": invalid}, 400)

    def test_well_formed_missing_quiz_is404(self):
        self.assert_denied({"quiz_id": str(uuid.uuid4())}, 404)

    def test_missing_question_is404(self):
        self.assert_denied({"question_id": str(uuid.uuid4())}, 404)

    def test_question_must_belong_to_the_reported_quiz(self):
        other = Quiz.objects.create(title="Other fixture", creator=self.author, folder=self.author.root_folder)
        question = Question.objects.create(quiz=other, text="Other question", order=1)
        self.assert_denied({"question_id": str(question.id)}, 404)

    def test_unshared_private_and_restricted_quizzes_are403(self):
        for visibility in (0, 1):
            with self.subTest(visibility=visibility):
                self.quiz.visibility = visibility
                self.quiz.save(update_fields=["visibility"])
                self.assert_denied({}, 403)

    def test_trashed_quiz_is403_even_if_public_or_shared(self):
        trash, _ = Folder.objects.get_or_create(
            owner=self.author,
            folder_type=FolderType.TRASH,
            defaults={"name": Folder.DEFAULT_TRASH_NAME, "parent": self.author.root_folder},
        )
        self.quiz.folder = trash
        self.quiz.save(update_fields=["folder"])
        SharedQuiz.objects.create(quiz=self.quiz, user=self.reader)
        self.assert_denied({}, 403)

    def test_creator_cannot_report_their_own_question(self):
        self.client.force_authenticate(user=self.author)
        self.assert_denied({}, 400)

    def test_readable_link_only_and_public_reports_send_once_with_trimmed_escaped_text(self):
        for visibility in (2, 3):
            with self.subTest(visibility=visibility):
                self.notification.reset_mock()
                self.quiz.visibility = visibility
                self.quiz.save(update_fields=["visibility"])
                response = self.post({"issue": "  <script>fixture</script>  "})
                self.assertEqual(response.status_code, 201, response.data)
                self.notification.assert_called_once()
                kwargs = self.notification.call_args.kwargs
                self.assertEqual(kwargs["user"], self.author)
                self.assertIn("&lt;script&gt;fixture&lt;/script&gt;", kwargs["content"])
                self.assertNotIn("<script>", kwargs["content"])
                self.assertIn(str(self.question.id), kwargs["cta_url"])

    def test_active_invitation_and_collaborator_reports_keep_existing_access(self):
        self.quiz.visibility = 1
        self.quiz.save(update_fields=["visibility"])
        share = SharedQuiz.objects.create(quiz=self.quiz, user=self.reader)
        for allow_edit in (False, True):
            with self.subTest(allow_edit=allow_edit):
                self.notification.reset_mock()
                share.allow_edit = allow_edit
                share.save(update_fields=["allow_edit"])
                self.assertEqual(self.post().status_code, 201)
                self.notification.assert_called_once()

    def test_study_group_share_remains_readable(self):
        self.quiz.visibility = 1
        self.quiz.save(update_fields=["visibility"])
        group = StudyGroup.objects.create(name="Report fixture group")
        self.reader.study_groups.add(group)
        SharedQuiz.objects.create(quiz=self.quiz, study_group=group)
        self.assertEqual(self.post().status_code, 201)
        self.notification.assert_called_once()

    def test_revoked_share_prevents_further_notification(self):
        self.quiz.visibility = 1
        self.quiz.save(update_fields=["visibility"])
        share = SharedQuiz.objects.create(quiz=self.quiz, user=self.reader)
        self.assertEqual(self.post().status_code, 201)
        self.notification.assert_called_once()
        self.notification.reset_mock()
        share.delete()
        self.assert_denied({}, 403)

    def test_private_visibility_suspends_invitation_reports_without_notification(self):
        self.quiz.visibility = 0
        self.quiz.save(update_fields=["visibility"])
        share = SharedQuiz.objects.create(quiz=self.quiz, user=self.reader, allow_edit=True)
        self.assert_denied({}, 403)
        self.assertTrue(SharedQuiz.objects.filter(pk=share.pk, allow_edit=True).exists())

    def test_guest_report_has_no_empty_reply_address(self):
        self.client.force_authenticate(user=User.objects.create_guest_user())
        self.assertEqual(self.post().status_code, 201)
        self.notification.assert_called_once()
        self.assertEqual(self.notification.call_args.kwargs["reply_to"], [])

    def test_non_object_report_body_is400(self):
        for body in ([], "fixture", 42, None):
            with self.subTest(body=body):
                response = self.client.post(self.url, json.dumps(body), content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.notification.assert_not_called()

    def test_notification_failure_stays_recoverable500(self):
        self.notification.side_effect = RuntimeError("Synthetic notification outage")
        response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["error"], "Email sending failed")
        self.notification.assert_called_once()

    def test_oauth_requires_write_scope_for_valid_reports(self):
        call_command("register_mobile_oauth", verbosity=0)
        application = get_application_model().objects.get(client_id="testownik-mobile")
        self.client.force_authenticate(user=None)
        for scope, expected in (("quizzes:read", 403), ("quizzes:write", 201)):
            self.notification.reset_mock()
            token = AccessToken.objects.create(
                user=self.reader,
                application=application,
                token="report-fixture-" + str(uuid.uuid4()),
                scope=scope,
                expires=timezone.now() + timedelta(minutes=5),
            )
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
            response = self.post()
            self.assertEqual(response.status_code, expected, response.data)
            self.assertEqual(self.notification.call_count, int(expected == 201))

    def test_anonymous_report_never_sends(self):
        self.client.force_authenticate(user=None)
        response = self.post()
        self.assertIn(response.status_code, (401, 403))
        self.notification.assert_not_called()
