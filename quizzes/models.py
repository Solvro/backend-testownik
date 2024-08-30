import uuid

from django.db import models

from users.models import StudyGroup, User


class Quiz(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    maintainer = models.ForeignKey(User, on_delete=models.CASCADE)
    is_public = models.BooleanField(
        default=True,
        help_text="Każdy zalogowany użytkownik będzie mógł zobaczyć tę bazę",
    )
    allow_anonymous = models.BooleanField(
        default=False,
        help_text="Każdy, nawet niezalogowany użytkownik będzie mógł wyświetlić tę bazę wchodząc na link",
    )
    is_anonymous = models.BooleanField(
        default=False,
        help_text="Nie będzie wyświetlany autor testu, cały czas będzie można zgłosić błąd w pytaniu",
    )
    version = models.PositiveIntegerField(default=1)

    questions = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.title or f"Quiz {self.id}"

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "maintainer": (
                self.maintainer.full_name if not self.is_anonymous else "Anonimowy"
            ),
            "is_public": self.is_public,
            "is_anonymous": self.is_anonymous,
            "version": self.version,
            "questions": self.questions,
        }


class SharedQuiz(models.Model):
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

    def __str__(self):
        return f"{self.quiz.title} shared with {self.user or self.study_group}"


class QuizProgress(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    current_question = models.PositiveIntegerField(default=0)
    mastered_questions = models.JSONField(
        default=list, blank=True
    )  # list of question ids that were answered correctly and won't be repeated
    failed_questions = models.JSONField(
        default=list, blank=True
    )  # list of question ids that will be repeated until answered correctly enough times
    study_time = models.DurationField(default=0)
    last_activity = models.DateTimeField(auto_now=True)
