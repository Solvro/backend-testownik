from django.db.models import Count, Max, Q

from quizzes.models import AnswerRecord, QuizSession


def get_quiz_stats(quiz, user, *, include_per_question: bool = False) -> dict:
    """
    Compute aggregated quiz statistics for a specific user.

    Aggregates answer data across all sessions (active + archived) for the given quiz/user pair.
    Study time is taken from the active session only.

    Args:
        quiz: Quiz instance to compute stats for.
        user: User instance to compute stats for.
        include_per_question: If True, includes per-question breakdown in the result.

    Returns:
        A dict with aggregated stats ready to be passed to QuizStatsSerializer.
    """
    sessions = QuizSession.objects.filter(quiz=quiz, user=user)

    # Count sessions separately to avoid JOIN inflation when aggregating answers.
    sessions_count = sessions.count()
    last_activity_at = sessions.aggregate(last_activity_at=Max("updated_at"))["last_activity_at"]

    # Aggregate answer data directly from AnswerRecord to avoid cross-join row duplication.
    answer_aggregates = AnswerRecord.objects.filter(session__in=sessions).aggregate(
        total_answers=Count("id"),
        correct_answers=Count("id", filter=Q(was_correct=True)),
    )

    total_answers = answer_aggregates["total_answers"] or 0
    correct_answers = answer_aggregates["correct_answers"] or 0
    wrong_answers = total_answers - correct_answers

    accuracy = round(correct_answers / total_answers * 100, 2) if total_answers > 0 else 0.0

    active_session = sessions.filter(is_active=True).first()
    study_time_seconds = int(active_session.study_time.total_seconds()) if active_session else 0

    result = {
        "quiz_id": quiz.id,
        "total_answers": total_answers,
        "correct_answers": correct_answers,
        "wrong_answers": wrong_answers,
        "accuracy": accuracy,
        "study_time_seconds": study_time_seconds,
        "sessions_count": sessions_count,
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
