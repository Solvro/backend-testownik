from datetime import timedelta

from django.db.models import Avg, Count, Max, OuterRef, Q, Subquery, Sum

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
    session_aggregates = sessions.aggregate(
        sessions_count=Count("id"),
        unique_users_count=Count("user", distinct=True) if not user else Count("user", distinct=True),
        last_activity_at=Max("updated_at"),
        total_time=Sum("study_time"),
        avg_time=Avg("study_time", filter=Q(is_active=False) | Q(study_time__gt=timedelta(0))),
    )

    sessions_count = session_aggregates["sessions_count"] or 0
    unique_users_count = session_aggregates["unique_users_count"] or 0
    last_activity_at = session_aggregates["last_activity_at"]

    total_study_time_seconds = (
        int(session_aggregates["total_time"].total_seconds()) if session_aggregates["total_time"] else 0
    )
    average_study_time_seconds = (
        int(session_aggregates["avg_time"].total_seconds()) if session_aggregates["avg_time"] else 0
    )

    # For backward compatibility, also provide study_time_seconds as active session time or total time
    if user:
        active_study_time = sessions.filter(is_active=True).values_list("study_time", flat=True).first()
        study_time_seconds = int(active_study_time.total_seconds()) if active_study_time else 0
    else:
        study_time_seconds = average_study_time_seconds

    # Aggregate answer data directly from AnswerRecord to avoid cross-join row duplication.
    answer_aggregates = AnswerRecord.objects.filter(session__in=sessions).aggregate(
        total_answers=Count("id"),
        correct_answers=Count("id", filter=Q(was_correct=True)),
    )

    total_answers = answer_aggregates["total_answers"] or 0
    correct_answers = answer_aggregates["correct_answers"] or 0
    wrong_answers = total_answers - correct_answers

    accuracy = round(correct_answers / total_answers * 100, 2) if total_answers > 0 else 0.0

    # Aggregate first answers for accuracy
    first_answers = AnswerRecord.objects.filter(
        id=Subquery(
            AnswerRecord.objects.filter(session_id=OuterRef("session_id"), question_id=OuterRef("question_id"))
            .order_by("answered_at")
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
        "unique_users_count": unique_users_count if not user else None,
        "last_activity_at": last_activity_at,
    }

    if include_per_question:
        result["per_question"] = _get_per_question_stats(sessions)

    return result


def _get_per_question_stats(sessions) -> list[dict]:
    """
    Compute per-question statistics for the given sessions queryset.

    Returns a list of dicts with question_id, attempts, correct_attempts, and last_answered_at.
    """
    per_question = (
        AnswerRecord.objects.filter(session__in=sessions)
        .values("question_id")
        .annotate(
            attempts=Count("id"),
            correct_attempts=Count("id", filter=Q(was_correct=True)),
            last_answered_at=Max("answered_at"),
        )
        .order_by("question_id")
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
