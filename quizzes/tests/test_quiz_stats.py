"""
Tests for GET /quizzes/{id}/stats endpoint.
"""

from datetime import timedelta

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Answer, AnswerRecord, Question, Quiz, QuizSession
from users.models import User


def _make_user(email="test@example.com"):
    return User.objects.create(email=email, first_name="Test", last_name="User", student_number=email[:6])


class QuizStatsEmptyTestCase(APITestCase):
    """Stats endpoint with no recorded activity returns zeroed-out response."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_authenticate(user=self.user)
        self.quiz = Quiz.objects.create(title="Stats Quiz", maintainer=self.user)

    def test_stats_with_no_sessions_returns_zeros(self):
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["quiz_id"], str(self.quiz.id))
        self.assertEqual(response.data["total_answers"], 0)
        self.assertEqual(response.data["correct_answers"], 0)
        self.assertEqual(response.data["wrong_answers"], 0)
        self.assertEqual(response.data["accuracy"], 0.0)
        self.assertEqual(response.data["study_time_seconds"], 0)
        self.assertEqual(response.data["sessions_count"], 0)
        self.assertIsNone(response.data["last_activity_at"])

    def test_stats_without_per_question_does_not_include_it(self):
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("per_question", response.data)


class QuizStatsAggregationTestCase(APITestCase):
    """Stats endpoint correctly aggregates answers across sessions."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_authenticate(user=self.user)

        self.quiz = Quiz.objects.create(title="Stats Quiz", maintainer=self.user)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        self.a1_correct = Answer.objects.create(question=self.q1, order=1, text="Correct", is_correct=True)
        self.a1_wrong = Answer.objects.create(question=self.q1, order=2, text="Wrong", is_correct=False)
        self.q2 = Question.objects.create(quiz=self.quiz, order=2, text="Q2")
        self.a2_correct = Answer.objects.create(question=self.q2, order=1, text="Correct", is_correct=True)

    def _record(self, session, question, was_correct):
        return AnswerRecord.objects.create(
            session=session,
            question=question,
            selected_answers=[],
            was_correct=was_correct,
        )

    def test_stats_totals_from_active_session(self):
        session = QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)
        self._record(session, self.q1, True)
        self._record(session, self.q1, False)
        self._record(session, self.q2, True)

        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_answers"], 3)
        self.assertEqual(response.data["correct_answers"], 2)
        self.assertEqual(response.data["wrong_answers"], 1)
        self.assertEqual(response.data["sessions_count"], 1)

    def test_stats_aggregates_across_archived_and_active_sessions(self):
        archived = QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=False)
        self._record(archived, self.q1, True)
        self._record(archived, self.q2, False)

        active = QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)
        self._record(active, self.q1, True)

        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_answers"], 3)
        self.assertEqual(response.data["correct_answers"], 2)
        self.assertEqual(response.data["wrong_answers"], 1)
        self.assertEqual(response.data["sessions_count"], 2)

    def test_accuracy_calculation(self):
        session = QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)
        # 3 correct out of 4 → 75.0%
        self._record(session, self.q1, True)
        self._record(session, self.q1, True)
        self._record(session, self.q1, True)
        self._record(session, self.q2, False)

        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertAlmostEqual(response.data["accuracy"], 75.0, places=2)

    def test_accuracy_is_zero_when_no_answers(self):
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["accuracy"], 0.0)

    def test_accuracy_rounds_to_two_decimal_places(self):
        session = QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)
        # 1 correct out of 3 → 33.33%
        self._record(session, self.q1, True)
        self._record(session, self.q1, False)
        self._record(session, self.q2, False)

        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertAlmostEqual(response.data["accuracy"], 33.33, places=2)


class QuizStatsStudyTimeTestCase(APITestCase):
    """Stats endpoint returns study_time_seconds from the active session only."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_authenticate(user=self.user)
        self.quiz = Quiz.objects.create(title="Time Quiz", maintainer=self.user)

    def test_study_time_from_active_session(self):
        QuizSession.objects.create(
            quiz=self.quiz,
            user=self.user,
            is_active=True,
            study_time=timedelta(seconds=300),
        )

        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["study_time_seconds"], 300)

    def test_study_time_ignores_archived_sessions(self):
        # Archived session with lots of time — should NOT be included
        QuizSession.objects.create(
            quiz=self.quiz,
            user=self.user,
            is_active=False,
            study_time=timedelta(seconds=9999),
        )
        # Active session with smaller time
        QuizSession.objects.create(
            quiz=self.quiz,
            user=self.user,
            is_active=True,
            study_time=timedelta(seconds=120),
        )

        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["study_time_seconds"], 120)

    def test_study_time_is_zero_when_no_active_session(self):
        QuizSession.objects.create(
            quiz=self.quiz,
            user=self.user,
            is_active=False,
            study_time=timedelta(seconds=500),
        )

        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["study_time_seconds"], 0)


class QuizStatsPerQuestionTestCase(APITestCase):
    """Stats endpoint returns per_question breakdown only when requested."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_authenticate(user=self.user)

        self.quiz = Quiz.objects.create(title="Per-Q Quiz", maintainer=self.user)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        self.q2 = Question.objects.create(quiz=self.quiz, order=2, text="Q2")

        self.session = QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)
        AnswerRecord.objects.create(session=self.session, question=self.q1, selected_answers=[], was_correct=True)
        AnswerRecord.objects.create(session=self.session, question=self.q1, selected_answers=[], was_correct=False)
        AnswerRecord.objects.create(session=self.session, question=self.q2, selected_answers=[], was_correct=True)

    def test_per_question_not_included_by_default(self):
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("per_question", response.data)

    def test_per_question_included_when_requested(self):
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url, {"include": "per_question"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("per_question", response.data)

    def test_per_question_counts_are_correct(self):
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url, {"include": "per_question"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        per_q = {str(item["question_id"]): item for item in response.data["per_question"]}

        self.assertIn(str(self.q1.id), per_q)
        self.assertEqual(per_q[str(self.q1.id)]["attempts"], 2)
        self.assertEqual(per_q[str(self.q1.id)]["correct_attempts"], 1)

        self.assertIn(str(self.q2.id), per_q)
        self.assertEqual(per_q[str(self.q2.id)]["attempts"], 1)
        self.assertEqual(per_q[str(self.q2.id)]["correct_attempts"], 1)

    def test_per_question_has_last_answered_at(self):
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url, {"include": "per_question"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for item in response.data["per_question"]:
            self.assertIn("last_answered_at", item)
            self.assertIsNotNone(item["last_answered_at"])

    def test_per_question_aggregates_across_sessions(self):
        # Add an archived session with more records for q1
        archived = QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=False)
        AnswerRecord.objects.create(session=archived, question=self.q1, selected_answers=[], was_correct=True)

        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url, {"include": "per_question"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        per_q = {str(item["question_id"]): item for item in response.data["per_question"]}

        # q1: 2 from active + 1 from archived = 3 total
        self.assertEqual(per_q[str(self.q1.id)]["attempts"], 3)
        self.assertEqual(per_q[str(self.q1.id)]["correct_attempts"], 2)

    def test_per_question_include_via_comma_separated_param(self):
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url, {"include": "foo,per_question"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("per_question", response.data)

    def test_per_question_included_for_comma_separated_include_values(self):
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url, {"include": "foo,per_question"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("per_question", response.data)

    def test_per_question_included_for_repeated_include_query_params(self):
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(f"{url}?include=foo&include=per_question")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("per_question", response.data)

    def test_per_question_not_included_for_unknown_include_values(self):
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url, {"include": "foo,bar"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("per_question", response.data)


class QuizStatsIsolationTestCase(APITestCase):
    """Stats are isolated per user — one user cannot see another's stats."""

    def setUp(self):
        self.owner = _make_user("owner@example.com")
        self.other = _make_user("other@example.com")

        self.quiz = Quiz.objects.create(title="Shared Quiz", maintainer=self.owner, visibility=3)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")

        # other user records an answer
        other_session = QuizSession.objects.create(quiz=self.quiz, user=self.other, is_active=True)
        AnswerRecord.objects.create(session=other_session, question=self.q1, selected_answers=[], was_correct=True)

    def test_owner_sees_only_own_stats_with_zero_when_no_own_activity(self):
        self.client.force_authenticate(user=self.owner)
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_answers"], 0)
        self.assertEqual(response.data["sessions_count"], 0)

    def test_other_user_sees_only_own_stats(self):
        self.client.force_authenticate(user=self.other)
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_answers"], 1)
        self.assertEqual(response.data["correct_answers"], 1)
        self.assertEqual(response.data["sessions_count"], 1)


class QuizStatsPermissionsTestCase(APITestCase):
    """Stats endpoint enforces authentication and quiz visibility rules."""

    def setUp(self):
        self.owner = _make_user("owner@example.com")
        self.stranger = _make_user("stranger@example.com")
        self.private_quiz = Quiz.objects.create(title="Private Quiz", maintainer=self.owner, visibility=0)
        self.public_quiz = Quiz.objects.create(title="Public Quiz", maintainer=self.owner, visibility=3)

    def test_unauthenticated_user_gets_401(self):
        url = reverse("quiz-stats", kwargs={"pk": self.public_quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_stranger_cannot_access_private_quiz_stats(self):
        self.client.force_authenticate(user=self.stranger)
        url = reverse("quiz-stats", kwargs={"pk": self.private_quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_access_own_private_quiz_stats(self):
        self.client.force_authenticate(user=self.owner)
        url = reverse("quiz-stats", kwargs={"pk": self.private_quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_authenticated_user_can_access_public_quiz_stats(self):
        self.client.force_authenticate(user=self.stranger)
        url = reverse("quiz-stats", kwargs={"pk": self.public_quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_stats_for_nonexistent_quiz_returns_404(self):
        self.client.force_authenticate(user=self.owner)
        url = reverse("quiz-stats", kwargs={"pk": "00000000-0000-0000-0000-000000000000"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
