"""Term-scoped Wrapped aggregation.

Mirrors the per-quiz math in `quizzes/services/stats.py`, un-scoped from a
single quiz and run over a term window. Writes typed `WrappedReport` rows.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Count, OuterRef, Q, QuerySet, Subquery, Sum
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone

from quizzes.models import AnswerRecord, Question, Quiz, QuizSession
from users.models import Term

from . import config

GUEST = "guest"


def _tz():
    return timezone.get_current_timezone()


def term_window(term: Term) -> tuple[datetime, datetime]:
    """(start, end) datetimes for a term; `finish_date` is inclusive."""
    start = timezone.make_aware(datetime.combine(term.start_date, time.min))
    end = timezone.make_aware(datetime.combine(term.finish_date + timedelta(days=1), time.min))
    return start, end


# --- Ranking (non-guest users) ---------------------------------------------


def _raw_metrics(start: datetime, end: datetime) -> dict[Any, dict[str, float]]:
    metrics: dict[Any, dict[str, float]] = defaultdict(lambda: {"study": 0.0, "answers": 0, "active_days": 0})

    sessions = (
        QuizSession.objects.filter(started_at__gte=start, started_at__lt=end)
        .exclude(user__account_type=GUEST)
        .values("user")
        .annotate(study=Sum("study_time"))
    )
    for row in sessions:
        metrics[row["user"]]["study"] = row["study"].total_seconds() if row["study"] else 0.0

    answers = (
        AnswerRecord.objects.filter(answered_at__gte=start, answered_at__lt=end)
        .exclude(session__user__account_type=GUEST)
        .values("session__user")
        .annotate(answers=Count("id"))
    )
    for row in answers:
        metrics[row["session__user"]]["answers"] = row["answers"] or 0

    days = (
        AnswerRecord.objects.filter(answered_at__gte=start, answered_at__lt=end)
        .exclude(session__user__account_type=GUEST)
        .annotate(day=TruncDate("answered_at", tzinfo=_tz()))
        .values("session__user")
        .annotate(active_days=Count("day", distinct=True))
    )
    for row in days:
        metrics[row["session__user"]]["active_days"] = row["active_days"] or 0

    return metrics


def _percentile_ranks(metrics: dict[Any, dict[str, float]], key: str) -> dict[Any, float]:
    users = list(metrics)
    values = sorted(metrics[u][key] for u in users)
    n = len(values)
    return {u: bisect.bisect_right(values, metrics[u][key]) / n for u in users}


def compute_ranking(start: datetime, end: datetime) -> dict[Any, dict[str, Any]]:
    """Rank every active non-guest user by a composite score → 'top X%'."""
    metrics = _raw_metrics(start, end)
    users = list(metrics)
    if not users:
        return {}

    p_study = _percentile_ranks(metrics, "study")
    p_answers = _percentile_ranks(metrics, "answers")
    p_days = _percentile_ranks(metrics, "active_days")
    weights = config.COMPOSITE_WEIGHTS

    composite = {
        u: (weights["study"] * p_study[u] + weights["answers"] * p_answers[u] + weights["active_days"] * p_days[u])
        for u in users
    }

    order = sorted(users, key=lambda u: composite[u], reverse=True)
    n = len(order)
    ranking: dict[Any, dict[str, Any]] = {}
    for index, user_id in enumerate(order):
        rank = index + 1
        top_percent = max(1, round(rank / n * 100))
        ranking[user_id] = {
            "composite": composite[user_id],
            "percentile": (n - rank) / n if n > 1 else 1.0,
            "top_percent": top_percent,
            "percentile_fill": max(0, min(100, 100 - top_percent)),
        }
    return ranking


# --- Stats from two querysets ----------------------------------------------


def _first_attempt_accuracy(answers: QuerySet) -> int:
    first_sub = (
        AnswerRecord.objects.filter(session=OuterRef("session"), question=OuterRef("question"))
        .order_by("answered_at", "id")
        .values("id")[:1]
    )
    agg = answers.filter(id=Subquery(first_sub)).aggregate(
        total=Count("id"), correct=Count("id", filter=Q(was_correct=True))
    )
    total = agg["total"] or 0
    return round((agg["correct"] or 0) / total * 100) if total else 0


def compute_stats(
    sessions: QuerySet,
    answers: QuerySet,
    *,
    start: datetime,
    end: datetime,
    creator_user_id: Any | None = None,
) -> dict[str, Any] | None:
    """Compute all stat fields from a sessions + answers queryset pair.

    Returns None when there's no activity at all. When `creator_user_id` is
    given, also computes creator impact (others studying that user's quizzes).
    """
    session_agg = sessions.aggregate(total=Sum("study_time"), count=Count("id"))
    sessions_count = session_agg["count"] or 0
    total_seconds = session_agg["total"].total_seconds() if session_agg["total"] else 0.0
    total_answers = answers.count()
    if total_answers == 0 and sessions_count == 0:
        return None

    answer_agg = answers.aggregate(correct=Count("id", filter=Q(was_correct=True)))
    correct = answer_agg["correct"] or 0
    wrong = total_answers - correct
    percent = round(correct / total_answers * 100) if total_answers else 0

    active_days = (answers.annotate(day=TruncDate("answered_at", tzinfo=_tz())).values("day").distinct().count()) or 1

    # Rhythm.
    by_hour = (
        answers.annotate(hour=ExtractHour("answered_at", tzinfo=_tz()))
        .values("hour")
        .annotate(total=Count("id"), correct=Count("id", filter=Q(was_correct=True)))
    )
    totals = [0] * 24
    corrects = [0] * 24
    for row in by_hour:
        hour = row["hour"]
        if hour is not None:
            totals[hour] = row["total"]
            corrects[hour] = row["correct"]
    peak_count = max(totals)
    scale = peak_count or 1
    peak_hour = totals.index(peak_count) if peak_count else 22

    # Top quizzes.
    top_rows = (
        sessions.values("quiz__title").annotate(time=Sum("study_time")).order_by("-time")[: config.TOP_QUIZZES_LIMIT]
    )
    top_quizzes = []
    for index, row in enumerate(top_rows):
        seconds = row["time"].total_seconds() if row["time"] else 0
        top_quizzes.append(
            {
                "rank": index + 1,
                "name": row["quiz__title"] or "Bez nazwy",
                "value": int(seconds),
            }
        )

    # Hardest question.
    hardest_row = (
        answers.values("question_id", "question__order", "question__text", "question__quiz__title")
        .annotate(
            wrong=Count("id", filter=Q(was_correct=False)),
            correct=Count("id", filter=Q(was_correct=True)),
        )
        .filter(wrong__gt=0)
        .order_by("-wrong", "question_id")
        .first()
    )
    hardest: dict[str, Any] = {
        "hardest_question_number": None,
        "hardest_quiz_name": "",
        "hardest_text": "",
        "hardest_wrong": None,
        "hardest_correct": None,
        "hardest_image": "",
    }
    if hardest_row is not None:
        question = Question.objects.filter(id=hardest_row["question_id"]).first()
        hardest = {
            "hardest_question_number": hardest_row["question__order"],
            "hardest_quiz_name": hardest_row["question__quiz__title"] or "",
            "hardest_text": hardest_row["question__text"] or "",
            "hardest_wrong": hardest_row["wrong"],
            "hardest_correct": hardest_row["correct"],
            "hardest_image": (question.image if question else "") or "",
        }

    # Creator impact.
    creator: dict[str, Any] = {
        "creator_people": None,
        "creator_answers": None,
        "creator_hours": None,
    }
    if creator_user_id is not None:
        own_quiz_ids = list(Quiz.objects.filter(creator_id=creator_user_id).values_list("id", flat=True))
        if own_quiz_ids:
            impact = (
                AnswerRecord.objects.filter(
                    session__quiz_id__in=own_quiz_ids,
                    answered_at__gte=start,
                    answered_at__lt=end,
                )
                .exclude(session__user_id=creator_user_id)
                .aggregate(
                    answers=Count("id"),
                    people=Count("session__user", distinct=True),
                )
            )
            people = impact["people"] or 0
            if people > 0:
                other_time = (
                    QuizSession.objects.filter(
                        quiz_id__in=own_quiz_ids,
                        started_at__gte=start,
                        started_at__lt=end,
                    )
                    .exclude(user_id=creator_user_id)
                    .aggregate(total=Sum("study_time"))
                )
                other_seconds = other_time["total"].total_seconds() if other_time["total"] else 0
                creator = {
                    "creator_people": people,
                    "creator_answers": impact["answers"] or 0,
                    "creator_hours": int(other_seconds // 3600),
                }

    return {
        "study_minutes": round(total_seconds / 60),
        "sessions": sessions_count,
        "active_days": active_days,
        "total_answers": total_answers,
        "answers_per_session": round(total_answers / sessions_count) if sessions_count else 0,
        "correct": correct,
        "wrong": wrong,
        "accuracy_percent": percent,
        "first_attempt_percent": _first_attempt_accuracy(answers),
        "hours": [round(t / scale * 100) for t in totals],
        "correct_hours": [round(c / scale * 100) for c in corrects],
        "peak_hour": peak_hour,
        **hardest,
        **creator,
        "top_quizzes": top_quizzes,
    }


# --- Report writers ---------------------------------------------------------


def _save_report(defaults: dict[str, Any], top_quizzes: list[dict], **lookup) -> None:
    from .models import WrappedReport, WrappedTopQuiz

    with transaction.atomic():
        report, _ = WrappedReport.objects.update_or_create(defaults=defaults, **lookup)
        report.top_quizzes.all().delete()
        WrappedTopQuiz.objects.bulk_create(WrappedTopQuiz(report=report, **tq) for tq in top_quizzes)


def build_user_report(user_id: Any, term: Term, rank: dict[str, Any]) -> bool:
    """Generate one user's report for a term. Returns False if no activity."""
    start, end = term_window(term)
    sessions = QuizSession.objects.filter(user_id=user_id, started_at__gte=start, started_at__lt=end)
    answers = AnswerRecord.objects.filter(session__user_id=user_id, answered_at__gte=start, answered_at__lt=end)
    stats = compute_stats(sessions, answers, start=start, end=end, creator_user_id=user_id)
    if stats is None:
        return False

    top_quizzes = stats.pop("top_quizzes")
    _save_report(
        defaults={
            **stats,
            "is_global": False,
            "composite_score": rank["composite"],
            "percentile": rank["percentile"],
            "top_percent": rank["top_percent"],
            "percentile_fill": rank["percentile_fill"],
        },
        top_quizzes=top_quizzes,
        user_id=user_id,
        term=term,
    )
    return True


def build_global_report(term: Term) -> bool:
    """Generate the platform-wide report for a term (guests included)."""
    start, end = term_window(term)
    sessions = QuizSession.objects.filter(started_at__gte=start, started_at__lt=end)
    answers = AnswerRecord.objects.filter(answered_at__gte=start, answered_at__lt=end)
    stats = compute_stats(sessions, answers, start=start, end=end)
    if stats is None:
        return False

    top_quizzes = stats.pop("top_quizzes")
    _save_report(
        defaults={**stats, "is_global": True},
        top_quizzes=top_quizzes,
        user=None,
        term=term,
        is_global=True,
    )
    return True
