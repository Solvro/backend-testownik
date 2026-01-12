import uuid
from datetime import timedelta

from django.db import models

from users.models import StudyGroup, User

QUIZ_VISIBILITY_CHOICES = [
    (0, "Prywatny"),
    (1, "Dla udostępnionych"),
    (2, "Niepubliczny (z linkiem)"),
    (3, "Publiczny"),
]


class Folder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="subfolders",
    )
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="folders")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.owner})"


class Quiz(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    maintainer = models.ForeignKey(User, on_delete=models.CASCADE)
    visibility = models.PositiveIntegerField(choices=QUIZ_VISIBILITY_CHOICES, default=2)
    allow_anonymous = models.BooleanField(
        default=False,
        help_text="Każdy, nawet niezalogowany użytkownik będzie mógł wyświetlić tę bazę wchodząc na link",
    )
    is_anonymous = models.BooleanField(
        default=False,
        help_text="Nie będzie wyświetlany autor testu, cały czas będzie można zgłosić błąd w pytaniu",
    )
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    questions = models.JSONField(default=list, blank=True)
    folder = models.ForeignKey(Folder, on_delete=models.SET_NULL, null=True, blank=True, related_name="quizzes")

    def __str__(self):
        return self.title or f"Quiz {self.id}"

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "maintainer": (self.maintainer.full_name if not self.is_anonymous else "Anonimowy"),
            "visibility": self.visibility,
            "visibility_name": dict(QUIZ_VISIBILITY_CHOICES)[self.visibility],
            "is_anonymous": self.is_anonymous,
            "version": self.version,
            "questions": self.questions,
        }

    def to_search_result(self):
        return {
            "id": self.id,
            "title": self.title,
            "maintainer": (self.maintainer.full_name if not self.is_anonymous else "Anonimowy"),
            "is_anonymous": self.is_anonymous,
        }

    def can_edit(self, user):
        return (
            user == self.maintainer
            or self.sharedquiz_set.filter(user=user, allow_edit=True).exists()
            or self.sharedquiz_set.filter(study_group__in=user.study_groups.all(), allow_edit=True).exists()
        )


class SharedQuiz(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="shared_quizzes",
        null=True,
        blank=True,
    )
    study_group = models.ForeignKey(
        StudyGroup,
        on_delete=models.CASCADE,
        related_name="shared_quizzes",
        null=True,
        blank=True,
    )
    allow_edit = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.quiz.title} shared with {self.user or self.study_group}"


class QuizProgress(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    current_question = models.PositiveIntegerField(default=0)
    reoccurrences = models.JSONField(default=list, blank=True)
    correct_answers_count = models.PositiveIntegerField(default=0)
    wrong_answers_count = models.PositiveIntegerField(default=0)
    study_time = models.DurationField(default=timedelta)
    last_activity = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.quiz.title} - {self.user} - {self.current_question}"

    def to_dict(self):
        return {
            "current_question": self.current_question,
            "correct_answers_count": self.correct_answers_count,
            "wrong_answers_count": self.wrong_answers_count,
            "study_time": self.study_time.total_seconds(),
            "last_activity": self.last_activity,
            "reoccurrences": self.reoccurrences,
        }
