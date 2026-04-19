import uuid
from datetime import timedelta

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import ProtectedError, Q
from django.utils import timezone

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

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.owner})"

    @property
    def is_root(self):
        try:
            return self.root_owner is not None
        except self.__class__.root_owner.RelatedObjectDoesNotExist:
            return False

    def delete(self, *args, **kwargs):
        if self.is_root:
            raise ProtectedError(
                "Cannot delete root folder.",
                set([self]),
            )
        super().delete(*args, **kwargs)

    def has_edit_permission(self, user):
        """Check if user can edit content in this folder."""
        if user == self.owner:
            return True
        return self.shares.filter(
            Q(user=user) | Q(study_group__in=user.study_groups.all()),
            allow_edit=True,
        ).exists()


class SharedFolder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name="shares")
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name="shared_folders")
    study_group = models.ForeignKey(
        StudyGroup, on_delete=models.CASCADE, null=True, blank=True, related_name="shared_folders"
    )
    allow_edit = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(user__isnull=False, study_group__isnull=True) | Q(user__isnull=True, study_group__isnull=False)
                ),
                name="sharedfolder_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["folder", "user"],
                name="unique_sharedfolder_folder_user",
            ),
            models.UniqueConstraint(
                fields=["folder", "study_group"],
                name="unique_sharedfolder_folder_study_group",
            ),
        ]

    def __str__(self):
        return f"Folder {self.folder.name} shared with {self.user or self.study_group}"


class Quiz(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name="created_quizzes")
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
    folder = models.ForeignKey(Folder, on_delete=models.PROTECT, related_name="quizzes")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "quiz"
        verbose_name_plural = "quizzes"

    def __str__(self):
        return self.title or f"Quiz {self.id}"

    def get_average_rating(self):
        return self.ratings.aggregate(avg=models.Avg("score"))["avg"]

    def get_review_count(self):
        return self.ratings.count()

    def get_last_used_at(self, user):
        last_session = self.sessions.filter(user=user).order_by("-updated_at").first()

        if last_session:
            return last_session.updated_at

        return None

    def can_edit(self, user):
        return (
            self.folder.has_edit_permission(user)
            or self.sharedquiz_set.filter(user=user, allow_edit=True).exists()
            or self.sharedquiz_set.filter(study_group__in=user.study_groups.all(), allow_edit=True).exists()
        )


class QuestionType(models.IntegerChoices):
    CLOSED = 0, "Zamknięte"
    OPEN = 1, "Otwarte"
    TRUE_FALSE = 2, "Prawda/Fałsz"


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
    question_type = models.IntegerField(
        choices=QuestionType.choices,
        default=QuestionType.CLOSED,
    )
    tf_answer = models.BooleanField(null=True, blank=True)  # true/false answer

    is_flashcard = models.BooleanField(default=False)
    is_markdown_enabled = models.BooleanField(
        default=True, help_text="Określa, czy tekst pytania ma wspierać formatowanie Markdown"
    )

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
        if created:
            session.current_question = quiz.questions.order_by("?").first()
            session.save(update_fields=["current_question"])
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
    selected_answers = models.JSONField(
        default=list
    )  # List of Answer UUIDs for Closed questions, free-form text for OPEN, booelan values for TRUE_FALSE
    was_correct = models.BooleanField()

    class Meta:
        ordering = ["-answered_at"]

    def __str__(self):
        result = "✓" if self.was_correct else "✗"
        return f"{result} {self.question.text[:30]}"


class QuestionIssue(models.Model):
    """
    Records issues or errors reported by users for specific quiz questions.

    Allows users to flag problems with question content, answer options, or explanations.
    Can be submitted anonymously or by a logged-in user.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.user and self.user.email:
            reporter = self.user.email
        elif self.email:
            reporter = self.email
        else:
            reporter = "Anonymous"

        return f"Issue on Question(id={self.question_id}) by {reporter}"


class QuizRating(models.Model):
    """
    Represents a rating of a quiz (1-5)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="quiz_ratings")
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="ratings")
    score = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "quiz"], name="unique_user_quiz_rating")]

    def __str__(self):
        return f"QuizRating(id={self.id}, author={self.user} score={self.score})"


class Comment(models.Model):
    """
    Threaded comment attached to a Quiz (and optionally a specific Question
    within it). Deletion is soft — the record is kept to preserve thread
    structure while the serializer hides content/author on read.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    content = models.TextField()
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies")
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="comments")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, null=True, blank=True, related_name="comments")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment(id={self.id}, author={self.author})"

    @property
    def is_reply(self):
        return self.parent_id is not None

    def mark_as_deleted(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.author = None
        self.save(update_fields=["is_deleted", "deleted_at", "author"])
