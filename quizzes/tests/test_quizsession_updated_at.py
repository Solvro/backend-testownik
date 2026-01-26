from django.test import TransactionTestCase
from django.utils import timezone

from quizzes.models import QuizSession
from quizzes.serializers import QuizSessionSerializer


class QuizSessionUpdatedAtTests(TransactionTestCase):
    def test_updated_at_is_in_serialized_output(self):
        session = QuizSession()
        session.updated_at = timezone.now()
        data = QuizSessionSerializer(session).data
        self.assertIn("updated_at", data)
        self.assertIsNotNone(data["updated_at"])

    def test_updated_at_field_has_auto_now(self):
        field = QuizSession._meta.get_field("updated_at")
        self.assertTrue(getattr(field, "auto_now", False))

    def test_updated_at_is_read_only_in_serializer(self):
        self.assertIn("updated_at", QuizSessionSerializer.Meta.read_only_fields)
