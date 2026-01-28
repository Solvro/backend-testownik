import os
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def image_upload_path(instance, filename):
    """
    Generate upload path organized by date.

    Path format: images/YYYY/MM/DD/<uuid>.<ext>
    """

    now = timezone.now()
    ext = os.path.splitext(filename)[1].lower()
    return f"images/{now.year}/{now.month:02d}/{now.day:02d}/{instance.id}{ext}"


class UploadedImage(models.Model):
    """
    Stores uploaded image files with metadata.

    Used by Question and Answer models via ForeignKey.
    Supports copy-on-write semantics - multiple questions/answers
    can reference the same image.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    image = models.ImageField(upload_to=image_upload_path)
    original_filename = models.CharField(max_length=255, db_index=True)
    content_type = models.CharField(max_length=100)
    file_size = models.PositiveIntegerField(help_text="File size in bytes")
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="uploaded_images"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "Uploaded Image"
        verbose_name_plural = "Uploaded Images"
        indexes = [
            models.Index(fields=["uploaded_at", "uploaded_by"]),
        ]

    def __str__(self):
        return f"{self.original_filename} ({self.id})"

    @property
    def is_orphan(self):
        """Check if this image has no references."""
        return not self.questions.exists() and not self.answers.exists()

    def delete(self, *args, **kwargs):
        """Delete the file from storage when model is deleted."""
        image = self.image
        if image:
            image.delete(save=False)

        super().delete(*args, **kwargs)
