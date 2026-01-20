from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Answer, AnswerRecord, Question, Quiz, QuizSession
from users.models import User


def create_test_user(student_number, first_name="Test", last_name="User", email=None):
    """Helper function to create test users."""
    user = User.objects.create(
        first_name=first_name,
        last_name=last_name,
        student_number=student_number,
        email=email or f"test{student_number}@example.com",
    )
    user.set_password("testpass123")
    user.save()
    return user


class QuestionRepetitionLimitTestCase(APITestCase):
    """Tests for question repetition limit functionality."""

    def setUp(self):
        """Set up test data."""
        # Use helper function
        self.user1 = create_test_user("123456", email="test1@example.com")
        self.user2 = create_test_user("123457", email="test2@example.com")

        # Authenticate user
        self.client.force_authenticate(user=self.user1)

        # Create quiz with limit of 3 repetitions
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            description="Test quiz description",
            maintainer=self.user1,
            visibility=2,
            max_question_repetitions=3,
        )

        # Create question
        self.question = Question.objects.create(
            quiz=self.quiz,
            order=1,
            text="Test question?",
            multiple=False,
        )

        # Create answers
        self.answer_correct = Answer.objects.create(
            question=self.question,
            order=1,
            text="Correct answer",
            is_correct=True,
        )
        self.answer_wrong = Answer.objects.create(
            question=self.question,
            order=2,
            text="Wrong answer",
            is_correct=False,
        )

    def test_quiz_created_with_max_repetitions(self):
        """Test: Quiz is created with max_question_repetitions field."""
        self.assertEqual(self.quiz.max_question_repetitions, 3)

    def test_answer_within_limit(self):
        """Test: Answer is saved when limit is not exceeded."""
        url = f"/quizzes/{self.quiz.id}/answer/"

        # First answer
        response = self.client.post(
            url,
            {
                "question_id": str(self.question.id),
                "selected_answers": [str(self.answer_correct.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(AnswerRecord.objects.count(), 1)

        # Check fields in response
        self.assertIn("remaining_repetitions", response.data)
        self.assertIn("max_question_repetitions", response.data)
        self.assertIn("repetitions_used", response.data)

        self.assertEqual(response.data["max_question_repetitions"], 3)
        self.assertEqual(response.data["repetitions_used"], 1)
        self.assertEqual(response.data["remaining_repetitions"], 2)

    def test_multiple_answers_within_limit(self):
        """Test: Multiple answers are allowed until limit is reached."""
        url = f"/quizzes/{self.quiz.id}/answer/"

        # Answer 1
        response1 = self.client.post(
            url,
            {
                "question_id": str(self.question.id),
                "selected_answers": [str(self.answer_wrong.id)],
            },
            format="json",
        )
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response1.data["repetitions_used"], 1)
        self.assertEqual(response1.data["remaining_repetitions"], 2)

        # Answer 2
        response2 = self.client.post(
            url,
            {
                "question_id": str(self.question.id),
                "selected_answers": [str(self.answer_wrong.id)],
            },
            format="json",
        )
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response2.data["repetitions_used"], 2)
        self.assertEqual(response2.data["remaining_repetitions"], 1)

        # Answer 3 (last allowed)
        response3 = self.client.post(
            url,
            {
                "question_id": str(self.question.id),
                "selected_answers": [str(self.answer_correct.id)],
            },
            format="json",
        )
        self.assertEqual(response3.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response3.data["repetitions_used"], 3)
        self.assertEqual(response3.data["remaining_repetitions"], 0)

        self.assertEqual(AnswerRecord.objects.count(), 3)

    def test_answer_exceeding_limit(self):
        """Test: Answer attempt exceeding limit is blocked."""
        url = f"/quizzes/{self.quiz.id}/answer/"
        session = QuizSession.objects.create(quiz=self.quiz, user=self.user1)

        # Create 3 answers (limit reached)
        for _ in range(3):
            AnswerRecord.objects.create(
                session=session,
                question=self.question,
                selected_answers=[str(self.answer_wrong.id)],
                was_correct=False,
            )

        # Attempt 4th answer (exceeds limit)
        response = self.client.post(
            url,
            {
                "question_id": str(self.question.id),
                "selected_answers": [str(self.answer_correct.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertIn("Exceeded maximum number", response.data["error"])
        self.assertEqual(response.data["max_question_repetitions"], 3)
        self.assertEqual(response.data["attempts_used"], 3)
        self.assertEqual(response.data["remaining_attempts"], 0)

        # Verify no new answer was added
        self.assertEqual(AnswerRecord.objects.count(), 3)

    def test_unlimited_repetitions_when_zero(self):
        """Test: When max_question_repetitions=0, unlimited answers are allowed."""
        # Create quiz without limit
        quiz_unlimited = Quiz.objects.create(
            title="Unlimited Quiz",
            maintainer=self.user1,
            visibility=2,
            max_question_repetitions=0,
        )

        question_unlimited = Question.objects.create(
            quiz=quiz_unlimited,
            order=1,
            text="Question without limit?",
        )

        answer_unlimited = Answer.objects.create(
            question=question_unlimited,
            order=1,
            text="Answer",
            is_correct=True,
        )

        url = f"/quizzes/{quiz_unlimited.id}/answer/"

        # Answer multiple times (well above typical limit)
        for i in range(10):
            response = self.client.post(
                url,
                {
                    "question_id": str(question_unlimited.id),
                    "selected_answers": [str(answer_unlimited.id)],
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(AnswerRecord.objects.filter(question=question_unlimited).count(), 10)

    def test_reset_session_resets_counter(self):
        """Test: Session reset clears the repetition counter."""
        url = f"/quizzes/{self.quiz.id}/answer/"
        progress_url = f"/quizzes/{self.quiz.id}/progress/"

        # Answer 3 times (reach limit)
        for _ in range(3):
            response = self.client.post(
                url,
                {
                    "question_id": str(self.question.id),
                    "selected_answers": [str(self.answer_wrong.id)],
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # 4th answer attempt should be blocked
        response = self.client.post(
            url,
            {
                "question_id": str(self.question.id),
                "selected_answers": [str(self.answer_correct.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Reset session
        reset_response = self.client.delete(progress_url)
        self.assertEqual(reset_response.status_code, status.HTTP_200_OK)

        # Verify old session is inactive
        old_sessions = QuizSession.objects.filter(quiz=self.quiz, user=self.user1, is_active=False)
        self.assertEqual(old_sessions.count(), 1)

        # Should be able to answer again
        response = self.client.post(
            url,
            {
                "question_id": str(self.question.id),
                "selected_answers": [str(self.answer_correct.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["repetitions_used"], 1)
        self.assertEqual(response.data["remaining_repetitions"], 2)

    def test_different_users_have_separate_counters(self):
        """Test: Different users have separate repetition counters."""
        url = f"/quizzes/{self.quiz.id}/answer/"

        # User1 answers 3 times (reaches limit)
        for _ in range(3):
            response = self.client.post(
                url,
                {
                    "question_id": str(self.question.id),
                    "selected_answers": [str(self.answer_wrong.id)],
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # User1 cannot answer anymore
        response = self.client.post(
            url,
            {
                "question_id": str(self.question.id),
                "selected_answers": [str(self.answer_correct.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Switch to user2
        self.client.force_authenticate(user=self.user2)

        # User2 can answer (has their own counter)
        response = self.client.post(
            url,
            {
                "question_id": str(self.question.id),
                "selected_answers": [str(self.answer_correct.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["repetitions_used"], 1)
        self.assertEqual(response.data["remaining_repetitions"], 2)

    def test_different_questions_have_separate_counters(self):
        """Test: Different questions have separate counters."""
        # Create second question
        question2 = Question.objects.create(
            quiz=self.quiz,
            order=2,
            text="Second question?",
        )
        answer2 = Answer.objects.create(
            question=question2,
            order=1,
            text="Answer 2",
            is_correct=True,
        )

        url = f"/quizzes/{self.quiz.id}/answer/"

        # Answer question 1 three times (reach limit)
        for _ in range(3):
            response = self.client.post(
                url,
                {
                    "question_id": str(self.question.id),
                    "selected_answers": [str(self.answer_correct.id)],
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Question 1 has reached limit
        response = self.client.post(
            url,
            {
                "question_id": str(self.question.id),
                "selected_answers": [str(self.answer_correct.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Question 2 has its own counter - can answer
        response = self.client.post(
            url,
            {
                "question_id": str(question2.id),
                "selected_answers": [str(answer2.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["repetitions_used"], 1)
        self.assertEqual(response.data["remaining_repetitions"], 2)

    def test_serializer_fields_in_response(self):
        """Test: Serializer returns all required fields."""
        url = f"/quizzes/{self.quiz.id}/answer/"

        response = self.client.post(
            url,
            {
                "question_id": str(self.question.id),
                "selected_answers": [str(self.answer_correct.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Check all required fields
        required_fields = [
            "id",
            "question",
            "selected_answers",
            "was_correct",
            "answered_at",
            "remaining_repetitions",
            "max_question_repetitions",
            "repetitions_used",
        ]

        for field in required_fields:
            self.assertIn(field, response.data, f"Missing field {field} in response")

    def test_quiz_metadata_includes_max_repetitions(self):
        """Test: Quiz metadata includes max_question_repetitions."""
        url = f"/quizzes/{self.quiz.id}/"

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("max_question_repetitions", response.data)
        self.assertEqual(response.data["max_question_repetitions"], 3)


class QuizSessionModelTestCase(TestCase):
    """Tests for QuizSession model."""

    def setUp(self):
        self.user = create_test_user("123456", email="test@example.com")

        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            maintainer=self.user,
            max_question_repetitions=3,
        )

    def test_get_or_create_active_session(self):
        """Test: get_or_create_active method creates or returns active session."""
        # First attempt - should create session
        session1, created1 = QuizSession.get_or_create_active(self.quiz, self.user)
        self.assertTrue(created1)
        self.assertTrue(session1.is_active)

        # Second attempt - should return same session
        session2, created2 = QuizSession.get_or_create_active(self.quiz, self.user)
        self.assertFalse(created2)
        self.assertEqual(session1.id, session2.id)

    def test_only_one_active_session_per_user_quiz(self):
        """Test: Constraint - only one active session per user and quiz."""
        _session1 = QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)

        # Attempting to create second active session should fail
        with self.assertRaises(Exception):
            QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)
