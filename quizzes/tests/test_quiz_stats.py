"""
Tests for GET /quizzes/{id}/stats endpoint.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import AnswerRecord, Question, Quiz, QuizSession
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
        self.q2 = Question.objects.create(quiz=self.quiz, order=2, text="Q2")

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


class QuizStatsScopeTestCase(APITestCase):
    """Stats endpoint validates scope and supports per-user/global aggregations."""

    def setUp(self):
        self.owner = _make_user("owner-scope@example.com")
        self.other = _make_user("other-scope@example.com")

        self.quiz = Quiz.objects.create(title="Scope Quiz", maintainer=self.owner, visibility=3)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")

        owner_session = QuizSession.objects.create(quiz=self.quiz, user=self.owner, is_active=True)
        AnswerRecord.objects.create(session=owner_session, question=self.q1, selected_answers=[], was_correct=True)

        other_session = QuizSession.objects.create(quiz=self.quiz, user=self.other, is_active=True)
        AnswerRecord.objects.create(session=other_session, question=self.q1, selected_answers=[], was_correct=True)
        AnswerRecord.objects.create(session=other_session, question=self.q1, selected_answers=[], was_correct=False)

    def test_scope_me_returns_current_user_stats(self):
        self.client.force_authenticate(user=self.owner)
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url, {"scope": "me"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_answers"], 1)
        self.assertEqual(response.data["correct_answers"], 1)
        self.assertEqual(response.data["sessions_count"], 1)
        self.assertIsNone(response.data["unique_users_count"])

    def test_scope_all_returns_aggregated_stats(self):
        self.client.force_authenticate(user=self.owner)
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url, {"scope": "all"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_answers"], 3)
        self.assertEqual(response.data["correct_answers"], 2)
        self.assertEqual(response.data["wrong_answers"], 1)
        self.assertEqual(response.data["sessions_count"], 2)
        self.assertEqual(response.data["unique_users_count"], 2)

    def test_invalid_scope_returns_400(self):
        self.client.force_authenticate(user=self.owner)
        url = reverse("quiz-stats", kwargs={"pk": self.quiz.id})
        response = self.client.get(url, {"scope": "invalid"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("scope", response.data)


class QuizStatsTimelineWindowTestCase(APITestCase):
    """Timeline includes answers from old sessions when answer date is in range."""

    def setUp(self):
        self.user = _make_user("timeline-owner@example.com")
        self.client.force_authenticate(user=self.user)

        self.quiz = Quiz.objects.create(title="Timeline Quiz", maintainer=self.user, visibility=3)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")

    def test_timeline_includes_recent_answers_from_old_session(self):
        now = timezone.now()

        old_session = QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)
        QuizSession.objects.filter(id=old_session.id).update(started_at=now - timedelta(days=45))

        old_answer = AnswerRecord.objects.create(
            session=old_session,
            question=self.q1,
            selected_answers=[],
            was_correct=True,
        )
        AnswerRecord.objects.filter(id=old_answer.id).update(answered_at=now - timedelta(days=1))

        url = reverse("quiz-stats-timeline", kwargs={"pk": self.quiz.id})
        response = self.client.get(url, {"scope": "me"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        day_key = (now - timedelta(days=1)).date().isoformat()

        timeline_by_date = {item["date"]: item for item in response.data}
        self.assertIn(day_key, timeline_by_date)
        self.assertEqual(timeline_by_date[day_key]["total_answers"], 1)
        self.assertEqual(timeline_by_date[day_key]["correct_answers"], 1)


class QuizStatsChartsScopeTestCase(APITestCase):
    """Chart endpoints support scope=me/all and validate scope input."""

    def setUp(self):
        self.owner = _make_user("charts-owner@example.com")
        self.other = _make_user("charts-other@example.com")

        self.quiz = Quiz.objects.create(title="Charts Quiz", maintainer=self.owner, visibility=3)
        self.q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        self.q2 = Question.objects.create(quiz=self.quiz, order=2, text="Q2")

        now = timezone.now()

        owner_session = QuizSession.objects.create(quiz=self.quiz, user=self.owner, is_active=True)
        QuizSession.objects.filter(id=owner_session.id).update(started_at=now - timedelta(hours=2))

        AnswerRecord.objects.create(session=owner_session, question=self.q1, selected_answers=[], was_correct=False)
        owner_correct = AnswerRecord.objects.create(
            session=owner_session,
            question=self.q2,
            selected_answers=[],
            was_correct=True,
        )
        AnswerRecord.objects.filter(id=owner_correct.id).update(answered_at=now - timedelta(days=1))

        other_session = QuizSession.objects.create(quiz=self.quiz, user=self.other, is_active=True)
        QuizSession.objects.filter(id=other_session.id).update(started_at=now - timedelta(hours=1))

        AnswerRecord.objects.create(session=other_session, question=self.q1, selected_answers=[], was_correct=False)

        self.timeline_url = reverse("quiz-stats-timeline", kwargs={"pk": self.quiz.id})
        self.hardest_url = reverse("quiz-stats-hardest-questions", kwargs={"pk": self.quiz.id})
        self.hourly_url = reverse("quiz-stats-hourly", kwargs={"pk": self.quiz.id})

    def test_timeline_scope_me_vs_all(self):
        self.client.force_authenticate(user=self.owner)

        me_response = self.client.get(self.timeline_url, {"scope": "me"})
        all_response = self.client.get(self.timeline_url, {"scope": "all"})

        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(all_response.status_code, status.HTTP_200_OK)

        me_total_answers = sum(item["total_answers"] for item in me_response.data)
        all_total_answers = sum(item["total_answers"] for item in all_response.data)

        self.assertEqual(me_total_answers, 2)
        self.assertEqual(all_total_answers, 3)

    def test_hardest_questions_scope_me_vs_all(self):
        self.client.force_authenticate(user=self.owner)

        me_response = self.client.get(self.hardest_url, {"scope": "me"})
        all_response = self.client.get(self.hardest_url, {"scope": "all"})

        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(all_response.status_code, status.HTTP_200_OK)

        me_by_question = {str(item["question_id"]): item for item in me_response.data}
        all_by_question = {str(item["question_id"]): item for item in all_response.data}

        self.assertEqual(me_by_question[str(self.q1.id)]["wrong_answers"], 1)
        self.assertEqual(me_by_question[str(self.q1.id)]["total_answers"], 1)

        self.assertEqual(all_by_question[str(self.q1.id)]["wrong_answers"], 2)
        self.assertEqual(all_by_question[str(self.q1.id)]["total_answers"], 2)

    def test_hourly_scope_me_vs_all(self):
        self.client.force_authenticate(user=self.owner)

        me_response = self.client.get(self.hourly_url, {"scope": "me"})
        all_response = self.client.get(self.hourly_url, {"scope": "all"})

        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(all_response.status_code, status.HTTP_200_OK)

        me_sessions_sum = sum(item["sessions_count"] for item in me_response.data)
        all_sessions_sum = sum(item["sessions_count"] for item in all_response.data)

        self.assertEqual(me_sessions_sum, 1)
        self.assertEqual(all_sessions_sum, 2)

    def test_invalid_scope_returns_400_for_chart_endpoints(self):
        self.client.force_authenticate(user=self.owner)

        for url in (self.timeline_url, self.hardest_url, self.hourly_url):
            response = self.client.get(url, {"scope": "invalid"})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("scope", response.data)


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

    def test_scope_all_does_not_bypass_private_quiz_permissions(self):
        self.client.force_authenticate(user=self.stranger)
        url = reverse("quiz-stats", kwargs={"pk": self.private_quiz.id})
        response = self.client.get(url, {"scope": "all"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_scope_all_does_not_bypass_private_quiz_permissions_for_chart_endpoints(self):
        self.client.force_authenticate(user=self.stranger)
        timeline_url = reverse("quiz-stats-timeline", kwargs={"pk": self.private_quiz.id})
        hardest_url = reverse("quiz-stats-hardest-questions", kwargs={"pk": self.private_quiz.id})
        hourly_url = reverse("quiz-stats-hourly", kwargs={"pk": self.private_quiz.id})

        for url in (timeline_url, hardest_url, hourly_url):
            response = self.client.get(url, {"scope": "all"})
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_stats_for_nonexistent_quiz_returns_404(self):
        self.client.force_authenticate(user=self.owner)
        url = reverse("quiz-stats", kwargs={"pk": "00000000-0000-0000-0000-000000000000"})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
