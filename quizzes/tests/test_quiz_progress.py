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
        self.quiz = Quiz.objects.create(title="Test Quiz", maintainer=self.user)
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

    # --- POST Progress (Update Session) ---
    def test_update_progress_study_time(self):
        """Test updating study_time on session."""
        session, _ = QuizSession.get_or_create_active(self.quiz, self.user)
        url = reverse("quiz-progress", kwargs={"pk": self.quiz.id})

        response = self.client.post(url, {"study_time": 120.5}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        session.refresh_from_db()
        self.assertEqual(session.study_time, timedelta(seconds=120.5))

    def test_update_progress_current_question(self):
        """Test updating current_question_id on session."""
        session, _ = QuizSession.get_or_create_active(self.quiz, self.user)
        url = reverse("quiz-progress", kwargs={"pk": self.quiz.id})

        response = self.client.post(url, {"current_question_id": str(self.q2.id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        session.refresh_from_db()
        self.assertEqual(session.current_question, self.q2)

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

        self.quiz = Quiz.objects.create(title="Test Quiz", maintainer=self.user)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        self.a1_correct = Answer.objects.create(question=self.q1, order=1, text="Correct", is_correct=True)
        self.a1_wrong = Answer.objects.create(question=self.q1, order=2, text="Wrong", is_correct=False)
        self.q2 = Question.objects.create(quiz=self.quiz, order=2, text="Q2")

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
            "current_question_id": str(self.q2.id),
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


class LegacyProgressTestCase(APITestCase):
    """Test legacy /quiz/{id}/progress/ endpoint for backwards compatibility."""

    def setUp(self):
        self.user = User.objects.create(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
        )
        self.client.force_authenticate(user=self.user)

        self.quiz = Quiz.objects.create(title="Test Quiz", maintainer=self.user)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        Answer.objects.create(question=self.q1, order=1, text="A1", is_correct=True)

    def test_get_legacy_progress(self):
        """Test GET on legacy endpoint returns correct format."""
        url = reverse("quiz-progress", kwargs={"quiz_id": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Legacy format fields
        self.assertIn("current_question", response.data)
        self.assertIn("correct_answers_count", response.data)
        self.assertIn("wrong_answers_count", response.data)
        self.assertIn("study_time", response.data)
        self.assertIn("reoccurrences", response.data)

    def test_post_legacy_progress_updates_study_time(self):
        """Test POST on legacy endpoint updates study_time."""
        QuizSession.get_or_create_active(self.quiz, self.user)
        url = reverse("quiz-progress", kwargs={"quiz_id": self.quiz.id})

        response = self.client.post(url, {"study_time": 300}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        session = QuizSession.objects.get(quiz=self.quiz, user=self.user, is_active=True)
        self.assertEqual(session.study_time, timedelta(seconds=300))

    def test_delete_legacy_progress_resets(self):
        """Test DELETE on legacy endpoint creates new session."""
        old_session = QuizSession.objects.create(quiz=self.quiz, user=self.user)
        url = reverse("quiz-progress", kwargs={"quiz_id": self.quiz.id})

        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        old_session.refresh_from_db()
        self.assertFalse(old_session.is_active)
