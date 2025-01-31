import uuid

from django.db import models


class Alert(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, blank=True)
    content = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    dismissible = models.BooleanField(default=True)
    color = models.CharField(max_length=20, default="info")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title
