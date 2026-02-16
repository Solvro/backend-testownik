import uuid
from datetime import timedelta

from django.db import models
from django.db.models import Q, UniqueConstraint

from users.models import StudyGroup, User

QUIZ_VISIBILITY_CHOICES = [
    (0, "Prywatny"),
    (1, "Dla udostępnionych"),
    (2, "Niepubliczny (z linkiem)"),
    (3, "Publiczny"),
]


class Type(models.TextChoices):
    ARCHIVE = "archive", "Archive"
    REGULAR = "regular", "Regular"


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
    folder_type = models.CharField(max_length=10, choices=Type.choices, default=Type.REGULAR)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            UniqueConstraint(
                fields=["owner", "folder_type"], condition=Q(folder_type=Type.ARCHIVE), name="unique_archive_per_user"
            )
        ]

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
    folder = models.ForeignKey(Folder, on_delete=models.SET_NULL, null=True, blank=True, related_name="quizzes")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "quiz"
        verbose_name_plural = "quizzes"

    def __str__(self):
        return self.title or f"Quiz {self.id}"

    def can_edit(self, user):
        return (
            user == self.maintainer
            or self.sharedquiz_set.filter(user=user, allow_edit=True).exists()
            or self.sharedquiz_set.filter(study_group__in=user.study_groups.all(), allow_edit=True).exists()
        )


class Question(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    image_url = models.URLField(blank=True, null=True, max_length=512)
    image_upload = models.ForeignKey(
        "uploads.UploadedImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="questions",
    )
    explanation = models.TextField(blank=True)
    multiple = models.BooleanField(default=False)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"Q{self.order}: {self.text[:50]}"

    @property
    def image(self):
        if self.image_upload:
            return self.image_upload.image.url
        return self.image_url


class Answer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    order = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    image_url = models.URLField(blank=True, null=True, max_length=512)
    image_upload = models.ForeignKey(
        "uploads.UploadedImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="answers",
    )
    is_correct = models.BooleanField(default=False)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{'✓' if self.is_correct else '✗'} {self.text[:50]}"

    @property
    def image(self):
        if self.image_upload:
            return self.image_upload.image.url
        return self.image_url


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


class QuizSession(models.Model):
    """Tracks a user's quiz attempt session. Archived on reset, new session created."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="sessions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="quiz_sessions")
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    study_time = models.DurationField(default=timedelta)
    current_question = models.ForeignKey("Question", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["quiz", "user"],
                condition=models.Q(is_active=True),
                name="one_active_session_per_user_quiz",
            ),
        ]

    def __str__(self):
        status = "active" if self.is_active else "archived"
        return f"{self.quiz.title} - {self.user} ({status})"

    @classmethod
    def get_or_create_active(cls, quiz, user):
        """Get active session or create new one."""
        session, created = cls.objects.get_or_create(quiz=quiz, user=user, is_active=True)
        return session, created

    @property
    def correct_count(self):
        return self.answers.filter(was_correct=True).count()

    @property
    def wrong_count(self):
        return self.answers.filter(was_correct=False).count()


class AnswerRecord(models.Model):
    """Records each answer given by a user for history and analytics."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(QuizSession, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answer_records")
    answered_at = models.DateTimeField(auto_now_add=True)
    selected_answers = models.JSONField(default=list)  # List of Answer UUIDs
    was_correct = models.BooleanField()

    class Meta:
        ordering = ["-answered_at"]

    def __str__(self):
        result = "✓" if self.was_correct else "✗"
        return f"{result} {self.question.text[:30]}"
