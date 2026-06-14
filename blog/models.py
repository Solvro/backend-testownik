import uuid

from django.conf import settings
from django.db import models


class BlogPost(models.Model):
    """
    A news / announcement post served on the public blog.

    Posts are authored by staff via the Django admin and exposed read-only
    through the public API. Content is stored as raw Markdown and rendered on
    the frontend. A post becomes publicly visible once `is_published` is set
    and `published_at` is in the past (allowing scheduled publishing).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    content = models.TextField(help_text="Markdown content")
    excerpt = models.CharField(max_length=500, blank=True, help_text="Short summary for list views")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blog_posts",
    )
    is_published = models.BooleanField(default=False, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return self.title
