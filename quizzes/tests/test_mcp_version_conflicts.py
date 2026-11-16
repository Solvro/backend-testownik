from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from quizzes.mcp import QuizTools
from quizzes.models import Question, Quiz
from quizzes.serializers import QuestionSerializer
from users.models import User


class MCPVersionConflictTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="mcp-version@example.invalid", password="fixture-password")
        self.quiz = Quiz.objects.create(title="Original", creator=self.user, folder=self.user.root_folder)
        self.question = Question.objects.create(quiz=self.quiz, text="Original", order=1)
        self.tools = QuizTools(request=SimpleNamespace(user=self.user, auth=SimpleNamespace(scope="quizzes:write")))

    def test_mcp_question_edit_and_delete_advance_the_parent_version(self):
        edited = self.tools.edit_question(str(self.question.pk), text="Changed through MCP")
        self.assertEqual(edited["status"], "updated")
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.version, 2)
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, "Changed through MCP")
        deleted = self.tools.delete_question(str(self.question.pk))
        self.assertEqual(deleted["status"], "deleted")
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.version, 3)
        self.assertFalse(Question.objects.filter(pk=self.question.pk).exists())

    def test_cross_quiz_batch_locks_quizzes_in_consistent_order_and_retains_response_order(self):
        other = Quiz.objects.create(title="Other", creator=self.user, folder=self.user.root_folder)
        second = Question.objects.create(quiz=other, text="Other question", order=1)
        questions = sorted([self.question, second], key=lambda question: str(question.quiz_id), reverse=True)
        updates = [
            {"question_id": str(question.pk), "text": f"Updated {index}"} for index, question in enumerate(questions)
        ]
        order = []
        original = QuestionSerializer.save

        def record(serializer, **kwargs):
            order.append(str(serializer.instance.quiz_id))
            return original(serializer, **kwargs)

        with patch.object(QuestionSerializer, "save", record):
            response = self.tools.edit_questions(updates)
        self.assertEqual(response["status"], "updated")
        self.assertEqual(response["question_ids"], [str(question.pk) for question in questions])
        self.assertEqual(order, sorted([str(self.quiz.pk), str(other.pk)]))
        self.quiz.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((self.quiz.version, other.version), (2, 2))

    def test_mcp_edit_returns_an_error_when_question_was_removed_after_validation(self):
        original = QuestionSerializer.update

        def interleave(serializer, instance, validated_data):
            self.tools.delete_question(str(instance.pk))
            return original(serializer, instance, validated_data)

        with patch.object(QuestionSerializer, "update", interleave):
            result = self.tools.edit_question(str(self.question.pk), text="Lost race")
        self.assertIn("Reload the quiz", str(result["error"]))
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.version, 2)
