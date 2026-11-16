from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APITestCase

from quizzes.models import Answer, Question, Quiz
from quizzes.serializers import QuestionSerializer, QuizSerializer
from quizzes.views import QuizViewSet
from users.models import User


class QuizVersionConflictTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="version-fixture@example.invalid", password="fixture-password")
        self.client.force_authenticate(self.user)
        self.quiz = Quiz.objects.create(
            title="Original", description="Original description", creator=self.user, folder=self.user.root_folder
        )
        self.question = Question.objects.create(quiz=self.quiz, text="Original question", order=1)
        self.answer = Answer.objects.create(question=self.question, text="Original answer", is_correct=True, order=1)
        self.url = reverse("quiz-detail", kwargs={"pk": self.quiz.pk})

    def test_matching_version_updates_once_and_is_not_exposed_in_response(self):
        response = self.client.patch(self.url, {"title": "Saved", "expected_version": 1}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], 2)
        self.assertNotIn("expected_version", response.data)
        self.assertEqual(
            self.client.patch(self.url, {"title": "Retry", "expected_version": 1}, format="json").status_code, 409
        )
        self.quiz.refresh_from_db()
        self.assertEqual((self.quiz.title, self.quiz.version), ("Saved", 2))

    def test_stale_nested_edit_does_not_delete_or_change_questions(self):
        Quiz.objects.filter(pk=self.quiz.pk).update(version=2)
        response = self.client.patch(
            self.url, {"title": "Stale", "questions": [], "expected_version": 1}, format="json"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "quiz_version_conflict")
        self.quiz.refresh_from_db()
        self.assertEqual((self.quiz.title, self.quiz.version), ("Original", 2))
        self.assertTrue(Question.objects.filter(pk=self.question.pk).exists())
        self.assertTrue(Answer.objects.filter(pk=self.answer.pk).exists())

    def test_competing_edit_between_read_and_save_rejects_conditional_writer(self):
        original = QuizViewSet.perform_update
        competing = False

        def interleave(view, serializer):
            nonlocal competing
            if not competing:
                competing = True
                winner = self.client.patch(
                    self.url, {"title": "Winner", "description": "Concurrent edit"}, format="json"
                )
                self.assertEqual(winner.status_code, 200)
            return original(view, serializer)

        with patch.object(QuizViewSet, "perform_update", interleave):
            response = self.client.patch(self.url, {"title": "Stale", "expected_version": 1}, format="json")
        self.assertEqual(response.status_code, 409)
        self.quiz.refresh_from_db()
        self.assertEqual((self.quiz.title, self.quiz.description, self.quiz.version), ("Winner", "Concurrent edit", 2))

    def test_legacy_partial_write_preserves_other_fields_changed_after_read(self):
        original = QuizViewSet.perform_update
        competing = False

        def interleave(view, serializer):
            nonlocal competing
            if not competing:
                competing = True
                self.client.patch(self.url, {"description": "Concurrent description"}, format="json")
            return original(view, serializer)

        with patch.object(QuizViewSet, "perform_update", interleave):
            response = self.client.patch(self.url, {"title": "Legacy edit"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.quiz.refresh_from_db()
        self.assertEqual(
            (self.quiz.title, self.quiz.description, self.quiz.version), ("Legacy edit", "Concurrent description", 3)
        )

    def test_nested_save_failure_rolls_back_version_claim_and_quiz_fields(self):
        with (
            patch.object(QuizSerializer, "_sync_questions", side_effect=RuntimeError("Fixture nested write failure")),
            self.assertRaises(RuntimeError),
        ):
            self.client.patch(self.url, {"title": "Failed", "questions": [], "expected_version": 1}, format="json")
        self.quiz.refresh_from_db()
        self.assertEqual((self.quiz.title, self.quiz.version), ("Original", 1))
        self.assertTrue(Question.objects.filter(pk=self.question.pk).exists())

    def test_invalid_precondition_is_rejected_without_mutation(self):
        for version in (0, -1, "invalid", None, 2147483648, 10**30):
            response = self.client.patch(self.url, {"title": "Invalid", "expected_version": version}, format="json")
            self.assertEqual(response.status_code, 400)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.version, 1)

    def test_create_with_precondition_is_rejected(self):
        response = self.client.post(
            reverse("quiz-list"), {"title": "New", "questions": [], "expected_version": 1}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Quiz.objects.count(), 1)

    def assert_old_editor_version_is_rejected(self):
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.version, 2)
        stale = self.client.patch(self.url, {"questions": [], "expected_version": 1}, format="json")
        self.assertEqual(stale.status_code, 409)

    def test_direct_question_edit_invalidates_existing_editor_version(self):
        response = self.client.patch(
            reverse("question-detail", kwargs={"pk": self.question.pk}), {"text": "Concurrent question"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assert_old_editor_version_is_rejected()
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, "Concurrent question")

    def test_question_removed_after_validation_returns_recoverable_error_and_does_not_bump_version(self):
        original = QuestionSerializer.update
        question_url = reverse("question-detail", kwargs={"pk": self.question.pk})

        def interleave(serializer, instance, validated_data):
            removed = self.client.delete(question_url)
            self.assertEqual(removed.status_code, 200)
            return original(serializer, instance, validated_data)

        with patch.object(QuestionSerializer, "update", interleave):
            response = self.client.patch(question_url, {"text": "Lost race"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Reload the quiz", str(response.data["question"]))
        self.assertFalse(Question.objects.filter(pk=self.question.pk).exists())
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.version, 2)

    def test_direct_question_create_invalidates_existing_editor_version(self):
        response = self.client.post(
            reverse("question-list"),
            {
                "quiz": str(self.quiz.pk),
                "text": "Added question",
                "answers": [{"text": "Added answer", "is_correct": True, "order": 1}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assert_old_editor_version_is_rejected()
        self.assertEqual(self.quiz.questions.count(), 2)

    def test_direct_question_delete_invalidates_existing_editor_version(self):
        response = self.client.delete(reverse("question-detail", kwargs={"pk": self.question.pk}))
        self.assertEqual(response.status_code, 200)
        self.assert_old_editor_version_is_rejected()
        self.assertFalse(Question.objects.filter(pk=self.question.pk).exists())

    def test_bulk_question_create_invalidates_existing_editor_version(self):
        response = self.client.post(
            reverse("question-bulk-create"),
            {
                "quiz": str(self.quiz.pk),
                "questions": [
                    {"text": "Bulk question", "answers": [{"text": "Bulk answer", "is_correct": True, "order": 1}]}
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assert_old_editor_version_is_rejected()
        self.assertEqual(self.quiz.questions.count(), 2)
