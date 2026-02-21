"""
Tests for Quiz Progress and Answer Recording endpoints.
"""

from datetime import timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Answer, AnswerRecord, Question, Quiz, QuizSession
from users.models import User


class QuizProgressTestCase(APITestCase):
    """Test new progress endpoints (QuizSession-based)."""

    def setUp(self):
        self.user = User.objects.create(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
        )
        self.client.force_authenticate(user=self.user)

        # Create quiz with questions
        self.quiz = Quiz.objects.create(title="Test Quiz", creator=self.user, folder=self.user.root_folder)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        self.a1_correct = Answer.objects.create(question=self.q1, order=1, text="Correct", is_correct=True)
        self.a1_wrong = Answer.objects.create(question=self.q1, order=2, text="Wrong", is_correct=False)
        self.q2 = Question.objects.create(quiz=self.quiz, order=2, text="Q2")
        self.a2_correct = Answer.objects.create(question=self.q2, order=1, text="Correct", is_correct=True)

    # --- GET Progress ---
    def test_get_progress_creates_session(self):
        """Test that GET progress creates a session if none exists."""
        url = reverse("quiz-progress", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("id", response.data)
        self.assertTrue(response.data["is_active"])
        self.assertEqual(QuizSession.objects.count(), 1)

    def test_get_progress_returns_existing_session(self):
        """Test that GET progress returns existing active session."""
        session = QuizSession.objects.create(quiz=self.quiz, user=self.user)

        url = reverse("quiz-progress", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(session.id))

    # --- DELETE Progress (Reset) ---
    def test_reset_progress_creates_new_session(self):
        """Test that DELETE archives old session and creates new one."""
        old_session = QuizSession.objects.create(quiz=self.quiz, user=self.user)
        url = reverse("quiz-progress", kwargs={"pk": self.quiz.id})

        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        old_session.refresh_from_db()
        self.assertFalse(old_session.is_active)
        self.assertIsNotNone(old_session.ended_at)

        # New session created
        new_session = QuizSession.objects.filter(quiz=self.quiz, user=self.user, is_active=True).first()
        self.assertIsNotNone(new_session)
        self.assertNotEqual(new_session.id, old_session.id)


class RecordAnswerTestCase(APITestCase):
    """Test POST /quizzes/{id}/answer/ endpoint."""

    def setUp(self):
        self.user = User.objects.create(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
        )
        self.client.force_authenticate(user=self.user)

        self.quiz = Quiz.objects.create(title="Test Quiz", creator=self.user, folder=self.user.root_folder)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        self.a1_correct = Answer.objects.create(question=self.q1, order=1, text="Correct", is_correct=True)
        self.a1_wrong = Answer.objects.create(question=self.q1, order=2, text="Wrong", is_correct=False)
        self.q2 = Question.objects.create(quiz=self.quiz, order=2, text="Q2")
        self.a2_correct = Answer.objects.create(question=self.q2, order=1, text="Correct", is_correct=True)

    def test_record_correct_answer(self):
        """Test recording a correct answer."""
        url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.id})
        data = {
            "question_id": str(self.q1.id),
            "selected_answers": [str(self.a1_correct.id)],
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["was_correct"])

        # Verify AnswerRecord created
        self.assertEqual(AnswerRecord.objects.count(), 1)
        record = AnswerRecord.objects.first()
        self.assertTrue(record.was_correct)

    def test_record_wrong_answer(self):
        """Test recording a wrong answer."""
        url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.id})
        data = {
            "question_id": str(self.q1.id),
            "selected_answers": [str(self.a1_wrong.id)],
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["was_correct"])

    def test_record_answer_updates_session(self):
        """Test that recording answer can also update session state."""
        url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.id})
        data = {
            "question_id": str(self.q1.id),
            "selected_answers": [str(self.a1_correct.id)],
            "study_time": 60.0,
            "next_question": str(self.q2.id),
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        session = QuizSession.objects.get(quiz=self.quiz, user=self.user, is_active=True)
        self.assertEqual(session.study_time, timedelta(seconds=60))
        self.assertEqual(session.current_question, self.q2)

    def test_correct_count_updates_after_answers(self):
        """Test that correct_count property reflects answer records."""
        session, _ = QuizSession.get_or_create_active(self.quiz, self.user)

        # Record correct answer
        AnswerRecord.objects.create(session=session, question=self.q1, selected_answers=[], was_correct=True)
        self.assertEqual(session.correct_count, 1)

        # Record wrong answer
        AnswerRecord.objects.create(session=session, question=self.q1, selected_answers=[], was_correct=False)
        self.assertEqual(session.correct_count, 1)
        self.assertEqual(session.wrong_count, 1)

    # --- Error Cases ---
    def test_record_answer_missing_question_id(self):
        """Test that missing question_id returns 400."""
        url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.id})
        data = {"selected_answers": [str(self.a1_correct.id)]}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "question_id is required")

    def test_record_answer_invalid_question_uuid(self):
        """Test that invalid question_id UUID format returns 404."""
        url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.id})
        data = {
            "question_id": "not-a-valid-uuid",
            "selected_answers": [],
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "Question not found in this quiz")

    def test_record_answer_question_not_in_quiz(self):
        """Test that question from another quiz returns 404."""
        other_quiz = Quiz.objects.create(title="Other Quiz", creator=self.user, folder=self.user.root_folder)
        other_question = Question.objects.create(quiz=other_quiz, order=1, text="Other Q")

        url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.id})
        data = {
            "question_id": str(other_question.id),
            "selected_answers": [],
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_record_answer_invalid_answer_ids(self):
        """Test that invalid answer IDs return 400."""
        url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.id})
        data = {
            "question_id": str(self.q1.id),
            "selected_answers": [str(self.a2_correct.id)],  # Answer from q2, not q1
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("do not belong to this question", response.data["error"])

    def test_record_answer_invalid_study_time(self):
        """Test that invalid study_time format returns 400."""
        url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.id})
        data = {
            "question_id": str(self.q1.id),
            "selected_answers": [str(self.a1_correct.id)],
            "study_time": "not-a-number",
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "study_time must be a numeric value")

    def test_record_answer_invalid_next_question_uuid(self):
        """Test that invalid next_question UUID format returns 400."""
        url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.id})
        data = {
            "question_id": str(self.q1.id),
            "selected_answers": [str(self.a1_correct.id)],
            "next_question": "not-a-valid-uuid",
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "next_question must be a valid question in this quiz")

    def test_record_answer_next_question_not_in_quiz(self):
        """Test that next_question from another quiz returns 400."""
        other_quiz = Quiz.objects.create(title="Other Quiz", creator=self.user, folder=self.user.root_folder)
        other_question = Question.objects.create(quiz=other_quiz, order=1, text="Other Q")

        url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.id})
        data = {
            "question_id": str(self.q1.id),
            "selected_answers": [str(self.a1_correct.id)],
            "next_question": str(other_question.id),
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
