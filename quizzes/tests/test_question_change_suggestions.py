from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from quizzes.models import Answer, Comment, Folder, Question, QuestionChangeSuggestion, Quiz, SharedQuiz
from users.models import User


class QuestionChangeSuggestionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(email="owner@example.com", password="password")
        self.reporter = User.objects.create_user(email="reporter@example.com", password="password")
        self.editor = User.objects.create_user(email="editor@example.com", password="password")

        self.folder = Folder.objects.create(name="Owner folder", owner=self.owner)
        self.quiz = Quiz.objects.create(title="Quiz", creator=self.owner, folder=self.folder, visibility=2)
        self.question = Question.objects.create(quiz=self.quiz, order=1, text="Old question", multiple=False)
        self.answer_1 = Answer.objects.create(question=self.question, order=1, text="Old A", is_correct=True)
        self.answer_2 = Answer.objects.create(question=self.question, order=2, text="Old B", is_correct=False)

        SharedQuiz.objects.create(quiz=self.quiz, user=self.editor, allow_edit=True)

    def _create_suggestion(self):
        self.client.force_authenticate(user=self.reporter)
        response = self.client.post(
            "/api/comments/",
            {
                "quiz": self.quiz.id,
                "question": self.question.id,
                "content": "This question should be changed",
                "suggestion": {
                    "payload": {
                        "text": "New question",
                        "answers": [
                            {
                                "id": str(self.answer_1.id),
                                "order": 1,
                                "text": "Updated A",
                                "is_correct": False,
                            },
                            {
                                "order": 2,
                                "text": "Brand new answer",
                                "is_correct": True,
                            },
                        ],
                    }
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response

    @patch("quizzes.services.notifications.send_question_comment_emails_task")
    def test_create_comment_with_question_change_suggestion(self, mock_email_task):
        with self.captureOnCommitCallbacks(execute=True):
            response = self._create_suggestion()

        self.assertEqual(response.data["suggestion"]["status"], "pending")
        self.assertEqual(response.data["suggestion"]["base_quiz_version"], self.quiz.version)
        self.assertEqual(QuestionChangeSuggestion.objects.count(), 1)
        mock_email_task.enqueue.assert_called_once()

    @patch("quizzes.services.notifications.send_question_comment_emails_task")
    def test_editor_accepts_suggestion_and_patches_question(self, _mock_email_task):
        response = self._create_suggestion()
        comment_id = response.data["id"]

        self.client.force_authenticate(user=self.editor)
        response = self.client.post(f"/api/comments/{comment_id}/accept-suggestion/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "accepted")

        self.question.refresh_from_db()
        self.quiz.refresh_from_db()
        self.assertEqual(self.question.text, "New question")
        self.assertEqual(self.quiz.version, 2)
        self.assertFalse(Answer.objects.filter(id=self.answer_2.id).exists())
        self.assertTrue(self.question.answers.filter(text="Updated A", is_correct=False).exists())
        self.assertTrue(self.question.answers.filter(text="Brand new answer", is_correct=True).exists())

    @patch("quizzes.services.notifications.send_question_comment_emails_task")
    def test_reader_without_edit_access_cannot_accept_suggestion(self, _mock_email_task):
        response = self._create_suggestion()
        comment_id = response.data["id"]

        self.client.force_authenticate(user=self.reporter)
        response = self.client.post(f"/api/comments/{comment_id}/accept-suggestion/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("quizzes.services.notifications.send_question_comment_emails_task")
    def test_accept_suggestion_returns_conflict_when_quiz_changed(self, _mock_email_task):
        response = self._create_suggestion()
        comment_id = response.data["id"]

        self.quiz.version += 1
        self.quiz.save(update_fields=["version"])

        self.client.force_authenticate(user=self.editor)
        response = self.client.post(f"/api/comments/{comment_id}/accept-suggestion/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, "Old question")

    @patch("quizzes.services.notifications.send_question_comment_emails_task")
    def test_report_question_issue_creates_comment_with_suggestion(self, mock_email_task):
        self.client.force_authenticate(user=self.reporter)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/api/report-question-issue/",
                {
                    "quiz_id": self.quiz.id,
                    "question_id": self.question.id,
                    "issue": "Change this answer",
                    "suggestion": {"payload": {"text": "Reported question text"}},
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Comment.objects.count(), 1)
        self.assertEqual(response.data["suggestion"]["payload"]["text"], "Reported question text")
        mock_email_task.enqueue.assert_called_once()
