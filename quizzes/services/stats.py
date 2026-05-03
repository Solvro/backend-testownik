from datetime import timedelta

from django.db.models import Avg, Count, Max, OuterRef, Q, Subquery, Sum
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone

from quizzes.models import AnswerRecord, QuizSession


def get_quiz_stats(quiz, user=None, *, include_per_question: bool = False) -> dict:
    """
    Compute aggregated quiz statistics for a specific user or globally.

    Aggregates answer data across all sessions (active + archived).
    If user is provided, filters for that user. Otherwise aggregates for all users.

    Args:
        quiz: Quiz instance to compute stats for.
        user: Optional User instance. If None, computes global stats.
        include_per_question: If True, includes per-question breakdown in the result.

    Returns:
        A dict with aggregated stats ready to be passed to QuizStatsSerializer.
    """
    sessions = QuizSession.objects.filter(quiz=quiz)
    if user:
        sessions = sessions.filter(user=user)

    # Aggregate basic session stats in a single query to avoid extra round-trips.
    # unique_users_count is only meaningful for global scope.
    aggregate_kwargs = {
        "sessions_count": Count("id"),
        "last_activity_at": Max("updated_at"),
        "total_time": Sum("study_time"),
        # Why: exclude *active* sessions with no recorded time yet (a brand-new
        # session would otherwise drag the average toward 0). Archived sessions
        # with study_time=0 are kept — they reflect real, completed attempts.
        "avg_time": Avg("study_time", filter=Q(is_active=False) | Q(study_time__gt=timedelta(0))),
    }
    if user is None:
        aggregate_kwargs["unique_users_count"] = Count("user", distinct=True)

    session_aggregates = sessions.aggregate(**aggregate_kwargs)

    sessions_count = session_aggregates["sessions_count"] or 0
    unique_users_count = (session_aggregates["unique_users_count"] or 0) if user is None else None
    last_activity_at = session_aggregates["last_activity_at"]

    total_study_time_seconds = (
        int(session_aggregates["total_time"].total_seconds()) if session_aggregates["total_time"] else 0
    )
    average_study_time_seconds = (
        int(session_aggregates["avg_time"].total_seconds()) if session_aggregates["avg_time"] else 0
    )

    # study_time_seconds has a single semantic: active session time for user scope.
    # For global scope (user=None), there is no single active session, so return None.
    if user:
        active_study_time = sessions.filter(is_active=True).values_list("study_time", flat=True).first()
        study_time_seconds = int(active_study_time.total_seconds()) if active_study_time else 0
    else:
        study_time_seconds = None

    # Aggregate answer data directly from AnswerRecord to avoid cross-join row duplication.
    answer_aggregates = AnswerRecord.objects.filter(session__in=sessions).aggregate(
        total_answers=Count("id"),
        correct_answers=Count("id", filter=Q(was_correct=True)),
    )

    total_answers = answer_aggregates["total_answers"] or 0
    correct_answers = answer_aggregates["correct_answers"] or 0
    wrong_answers = total_answers - correct_answers

    accuracy = round(correct_answers / total_answers * 100, 2) if total_answers > 0 else 0.0

    # Aggregate first answers for accuracy. The `id` tiebreaker keeps the
    # picked row deterministic when two answers share `answered_at`.
    first_answers = AnswerRecord.objects.filter(
        id=Subquery(
            AnswerRecord.objects.filter(session_id=OuterRef("session_id"), question_id=OuterRef("question_id"))
            .order_by("answered_at", "id")
            .values("id")[:1]
        )
    ).filter(session__in=sessions)

    first_aggregates = first_answers.aggregate(total=Count("id"), correct=Count("id", filter=Q(was_correct=True)))
    first_total = first_aggregates["total"] or 0
    first_correct = first_aggregates["correct"] or 0
    first_answer_accuracy = round(first_correct / first_total * 100, 2) if first_total > 0 else 0.0

    result = {
        "quiz_id": quiz.id,
        "total_answers": total_answers,
        "correct_answers": correct_answers,
        "wrong_answers": wrong_answers,
        "accuracy": accuracy,
        "first_answer_accuracy": first_answer_accuracy,
        "study_time_seconds": study_time_seconds,
        "total_study_time_seconds": total_study_time_seconds,
        "average_study_time_seconds": average_study_time_seconds,
        "sessions_count": sessions_count,
        "unique_users_count": unique_users_count,
        "last_activity_at": last_activity_at,
    }

    if include_per_question:
        result["per_question"] = _get_per_question_stats(sessions)

    return result


def _get_per_question_stats(sessions) -> list[dict]:
    """
    Compute per-question statistics for the given sessions queryset.

    Returns a list of dicts with question_id, attempts, correct_attempts, and
    last_answered_at, ordered by the question's display `order`.
    """
    per_question = (
        AnswerRecord.objects.filter(session__in=sessions)
        .values("question_id", "question__order")
        .annotate(
            attempts=Count("id"),
            correct_attempts=Count("id", filter=Q(was_correct=True)),
            last_answered_at=Max("answered_at"),
        )
        .order_by("question__order", "question_id")
    )

    return [
        {
            "question_id": row["question_id"],
            "attempts": row["attempts"],
            "correct_attempts": row["correct_attempts"],
            "last_answered_at": row["last_answered_at"],
        }
        for row in per_question
    ]


def get_quiz_timeline_stats(quiz, user=None, days: int = 30) -> list[dict]:
    """
    Compute timeline statistics (last N days) for a quiz.

    Returns a list with one entry per calendar day in the trailing window
    (including days with no activity, filled with zeros). Each entry has:
    `date`, `sessions_count`, `total_answers`, `correct_answers`,
    `total_study_time_seconds`.

    `sessions_count` and `total_study_time_seconds` are bucketed by `started_at`.
    `total_answers` / `correct_answers` are bucketed by `answered_at`, so answers
    from older sessions still count when answered within the window.
    """
    now = timezone.now()
    start_date = now - timedelta(days=days)

    sessions = QuizSession.objects.filter(quiz=quiz)
    if user:
        sessions = sessions.filter(user=user)

    sessions_by_date = (
        sessions.filter(started_at__gte=start_date)
        .annotate(date=TruncDate("started_at"))
        .values("date")
        .annotate(
            sessions_count=Count("id"),
            study_time=Sum("study_time"),
        )
        .order_by("date")
    )

    answers = AnswerRecord.objects.filter(session__quiz=quiz, answered_at__gte=start_date)
    if user:
        answers = answers.filter(session__user=user)

    answers_by_date = (
        answers.annotate(date=TruncDate("answered_at"))
        .values("date")
        .annotate(
            total_answers=Count("id"),
            correct_answers=Count("id", filter=Q(was_correct=True)),
        )
        .order_by("date")
    )

    # Pre-fill every day in the window so charts have a continuous x-axis.
    today = now.date()
    data_by_date: dict[str, dict] = {}
    for offset in range(days + 1):
        day = today - timedelta(days=offset)
        data_by_date[day.isoformat()] = {
            "date": day.isoformat(),
            "sessions_count": 0,
            "total_answers": 0,
            "correct_answers": 0,
            "total_study_time_seconds": 0,
        }

    for row in sessions_by_date:
        if not row["date"]:
            continue
        key = row["date"].isoformat()
        bucket = data_by_date.setdefault(
            key,
            {
                "date": key,
                "sessions_count": 0,
                "total_answers": 0,
                "correct_answers": 0,
                "total_study_time_seconds": 0,
            },
        )
        bucket["sessions_count"] = row["sessions_count"]
        bucket["total_study_time_seconds"] = int(row["study_time"].total_seconds()) if row["study_time"] else 0

    for row in answers_by_date:
        if not row["date"]:
            continue
        key = row["date"].isoformat()
        bucket = data_by_date.setdefault(
            key,
            {
                "date": key,
                "sessions_count": 0,
                "total_answers": 0,
                "correct_answers": 0,
                "total_study_time_seconds": 0,
            },
        )
        bucket["total_answers"] = row["total_answers"]
        bucket["correct_answers"] = row["correct_answers"]

    return sorted(data_by_date.values(), key=lambda x: x["date"])


def get_quiz_sessions_stats(quiz, user=None, days: int = 30) -> list[dict]:
    """
    Return one entry per quiz session within the trailing window, in chronological
    order. Powers the "score over time" and "study time over time" line charts:
    each session is a single data point on the x-axis (started_at).

    Each entry: `session_id`, `started_at`, `ended_at`, `study_time_seconds`,
    `total_answers`, `correct_answers`, `accuracy`.
    """
    start_date = timezone.now() - timedelta(days=days)

    sessions = QuizSession.objects.filter(quiz=quiz, started_at__gte=start_date)
    if user:
        sessions = sessions.filter(user=user)

    sessions = sessions.annotate(
        total_answers=Count("answers"),
        correct_answers=Count("answers", filter=Q(answers__was_correct=True)),
    ).order_by("started_at")

    result = []
    for session in sessions.values(
        "id",
        "started_at",
        "ended_at",
        "study_time",
        "total_answers",
        "correct_answers",
    ):
        total = session["total_answers"] or 0
        correct = session["correct_answers"] or 0
        accuracy = round(correct / total * 100, 2) if total > 0 else 0.0
        result.append(
            {
                "session_id": session["id"],
                "started_at": session["started_at"],
                "ended_at": session["ended_at"],
                "study_time_seconds": (int(session["study_time"].total_seconds()) if session["study_time"] else 0),
                "total_answers": total,
                "correct_answers": correct,
                "accuracy": accuracy,
            }
        )
    return result


def get_quiz_hardest_questions(quiz, user=None, limit: int = 10) -> list[dict]:
    """
    Get the top N hardest questions (most wrong answers) for a quiz.

    Each entry includes the question text so charts can label slices without
    a follow-up round-trip.
    """
    sessions = QuizSession.objects.filter(quiz=quiz)
    if user:
        sessions = sessions.filter(user=user)

    hardest = (
        AnswerRecord.objects.filter(session__in=sessions)
        .values("question_id", "question__text")
        .annotate(wrong_answers=Count("id", filter=Q(was_correct=False)), total_answers=Count("id"))
        .filter(wrong_answers__gt=0)
        .order_by("-wrong_answers", "question_id")[:limit]
    )

    return [
        {
            "question_id": row["question_id"],
            "question_text": row["question__text"],
            "wrong_answers": row["wrong_answers"],
            "total_answers": row["total_answers"],
        }
        for row in hardest
    ]


def get_quiz_hourly_stats(quiz, user=None) -> list[dict]:
    """
    Get 24h radar chart data (activity grouped by hour of day).
    """
    sessions = QuizSession.objects.filter(quiz=quiz)
    if user:
        sessions = sessions.filter(user=user)

    hourly = (
        sessions.annotate(hour=ExtractHour("started_at"))
        .values("hour")
        .annotate(sessions_count=Count("id"))
        .order_by("hour")
    )

    # Fill missing hours with 0
    hourly_dict = {row["hour"]: row["sessions_count"] for row in hourly if row["hour"] is not None}
    return [{"hour": h, "sessions_count": hourly_dict.get(h, 0)} for h in range(24)]
