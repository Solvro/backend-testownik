import uuid

from django.conf import settings
from django.db import models


class LoginAttempt(models.Model):
    """Short-lived, PKCE-bound native login. Tokens never travel in a redirect."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=10)
    challenge = models.CharField(max_length=43)
    state = models.CharField(max_length=128)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)
    guest = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="mobile_login_attempts"
    )
    code_hash = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    consumed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.provider} login {self.pk}"


class AnswerReceipt(models.Model):
    """Persisted idempotency result, including after the original session is reset."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    request_id = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    response = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "request_id"], name="mobile_answer_once")]

    def __str__(self):
        return f"{self.user_id}: {self.request_id}"


class QuizCreateReceipt(models.Model):
    """One durable create outcome, retained even if the created quiz is deleted."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    request_id = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    outcome = models.CharField(max_length=10, choices=[("created", "Created"), ("rejected", "Rejected")])
    quiz = models.ForeignKey("quizzes.Quiz", null=True, on_delete=models.SET_NULL)
    original_quiz_id = models.UUIDField(null=True)
    created_version = models.PositiveIntegerField(null=True)
    id_map = models.JSONField(default=dict)
    validation_errors = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "request_id"], name="mobile_quiz_create_once")]

    def __str__(self):
        return f"{self.user_id}: {self.request_id}"
