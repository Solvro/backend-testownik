from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Answer, Question, Quiz, QuizSession
from users.models import User


class RecordAnswerUpdatesSessionTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com", password="password", first_name="Test", last_name="User"
        )
        self.client.force_authenticate(user=self.user)

        self.quiz = Quiz.objects.create(title="Test Quiz", maintainer=self.user)
        self.question = Question.objects.create(quiz=self.quiz, order=1, text="Question 1")
        self.answer = Answer.objects.create(question=self.question, order=1, text="Answer 1", is_correct=True)

        self.url = reverse("quiz-detail", kwargs={"pk": self.quiz.id}) + "answer/"

    def test_record_answer_updates_session_timestamp(self):
        # 1. Start a session explicitly or let the view create it
        session, _ = QuizSession.get_or_create_active(self.quiz, self.user)
        original_updated_at = session.updated_at

        # Ensure some time passes or mock time if needed,
        # but since we are in a real DB test, we might run too fast.
        # Let's manually set updated_at to the past to be sure.
        session.updated_at = timezone.now() - timedelta(minutes=10)
        session.save()
        original_updated_at = session.updated_at  # refresh

        # 2. Record answer
        data = {"question_id": self.question.id, "selected_answers": [self.answer.id]}
        response = self.client.post(self.url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # 3. Reload session
        session.refresh_from_db()

        # 4. Verify updated_at is recent (changed)
        self.assertNotEqual(session.updated_at, original_updated_at)
        self.assertTrue(session.updated_at > original_updated_at)
