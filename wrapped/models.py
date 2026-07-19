import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from users.models import Term

from . import config


class WrappedReport(models.Model):
    """A precomputed Wrapped for one user (or the whole platform) in one term."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wrapped_reports",
        null=True,
        blank=True,
    )
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="wrapped_reports")
    is_global = models.BooleanField(default=False, db_index=True)
    generated_at = models.DateTimeField(auto_now=True)

    # Ranking (0 for the global report)
    composite_score = models.FloatField(default=0.0)
    percentile = models.FloatField(default=0.0, help_text="Fraction of users this user beat (0–1).")

    # Study time
    study_minutes = models.PositiveIntegerField(default=0)
    sessions = models.PositiveIntegerField(default=0)
    active_days = models.PositiveIntegerField(default=0)

    # Volume
    total_answers = models.PositiveIntegerField(default=0)
    answers_per_session = models.PositiveIntegerField(default=0)

    # Accuracy
    correct = models.PositiveIntegerField(default=0)
    wrong = models.PositiveIntegerField(default=0)
    accuracy_percent = models.PositiveIntegerField(default=0)
    first_attempt_percent = models.PositiveIntegerField(default=0)

    # Rhythm (24-element arrays, 0–100)
    hours = models.JSONField(default=list)
    correct_hours = models.JSONField(default=list)
    peak_hour = models.PositiveIntegerField(default=0)

    # Rank display
    top_percent = models.PositiveIntegerField(default=0)
    percentile_fill = models.PositiveIntegerField(default=0)

    # Hardest question (all null when there isn't one)
    hardest_question_number = models.PositiveIntegerField(null=True, blank=True)
    hardest_quiz_name = models.CharField(max_length=255, blank=True, default="")
    hardest_text = models.TextField(blank=True, default="")
    hardest_wrong = models.PositiveIntegerField(null=True, blank=True)
    hardest_correct = models.PositiveIntegerField(null=True, blank=True)
    hardest_image = models.URLField(max_length=512, blank=True, default="")

    # Creator impact (all null when there isn't any)
    creator_people = models.PositiveIntegerField(null=True, blank=True)
    creator_answers = models.PositiveIntegerField(null=True, blank=True)
    creator_hours = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-generated_at"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(is_global=True, user__isnull=True) | Q(is_global=False, user__isnull=False)),
                name="wrapped_global_user_consistency",
            ),
            models.UniqueConstraint(
                fields=["user", "term"],
                condition=Q(is_global=False, user__isnull=False),
                name="one_wrapped_per_user_term",
            ),
            models.UniqueConstraint(
                fields=["term"],
                condition=Q(is_global=True, user__isnull=True),
                name="one_global_wrapped_per_term",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "term"]),
            models.Index(fields=["term", "is_global"]),
        ]

    def __str__(self):
        who = "GLOBAL" if self.is_global else str(self.user_id)
        return f"Wrapped {self.term_id} · {who}"

    def to_payload(self) -> dict:
        """Assemble the exact `WrappedData` shape the frontend consumes."""
        hardest = None
        if self.hardest_question_number is not None:
            hardest = {
                "question_number": self.hardest_question_number,
                "quiz_name": self.hardest_quiz_name,
                "text": self.hardest_text,
                "wrong_count": self.hardest_wrong,
                "correct_count": self.hardest_correct,
                "image": self.hardest_image or None,
            }
        creator = None
        if self.creator_people is not None:
            creator = {
                "people": self.creator_people,
                "answers": self.creator_answers,
                "hours": self.creator_hours,
            }
        return {
            "is_empty": False,
            "is_global": self.is_global,
            "season": config.season_block(self.term, timezone.localdate(self.generated_at)),
            "study_time": {"total_minutes": self.study_minutes},
            "volume": {
                "total_answers": self.total_answers,
                "sessions": self.sessions,
                "answers_per_session": self.answers_per_session,
            },
            "accuracy": {
                "percent": self.accuracy_percent,
                "correct": self.correct,
                "wrong": self.wrong,
                "first_attempt_percent": self.first_attempt_percent,
            },
            "rhythm": {
                "hours": self.hours,
                "correct_hours": self.correct_hours,
                "peak_hour": self.peak_hour,
            },
            "top_quizzes": [tq.as_dict() for tq in self.top_quizzes.all()],
            "hardest_question": hardest,
            "creator_impact": creator,
            "rank": {
                "top_percent": self.top_percent,
                "percentile_fill": self.percentile_fill,
            },
        }


class WrappedTopQuiz(models.Model):
    """One row of the 'top quizzes by time' list on a report."""

    report = models.ForeignKey(WrappedReport, on_delete=models.CASCADE, related_name="top_quizzes")
    rank = models.PositiveIntegerField()
    name = models.CharField(max_length=255)
    value = models.PositiveIntegerField(help_text="Study seconds, for bar scaling.")

    class Meta:
        ordering = ["rank"]

    def __str__(self):
        return f"#{self.rank} {self.name}"

    def as_dict(self) -> dict:
        return {
            "rank": self.rank,
            "name": self.name,
            "value": self.value,
        }
