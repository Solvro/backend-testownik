import uuid

from django.db import models

from users.models import User


class NotificationType(models.TextChoices):
    """
    Enumeration of notification types available in the system.

    Attributes:
        EMAIL: Delivered via e-mail.
        IN_APP: Visible only inside the application's notification list.
        PUSH: Delivered via Web Push to subscribed devices (future delivery).
    """

    EMAIL = "email", "Email"
    IN_APP = "in_app", "In App"
    PUSH = "push", "Push"


class Notification(models.Model):
    """
    Represents a notification entity that can be sent to users.

    Notifications can be sent via email or displayed in-app. Each notification
    is associated with a user and tracks whether it has been read.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=128)
    content = models.TextField()
    is_read = models.BooleanField(default=False)
    notification_type = models.CharField(max_length=20, choices=NotificationType.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Notification(id={self.id}, title={self.title}, user={self.user_id})"
