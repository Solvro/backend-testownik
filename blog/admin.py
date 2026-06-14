from django.contrib import admin
from django.utils import timezone
from unfold.admin import ModelAdmin

from .forms import BlogPostAdminForm
from .models import BlogPost


@admin.register(BlogPost)
class BlogPostAdmin(ModelAdmin):
    form = BlogPostAdminForm
    list_display = ["title", "is_published", "published_at", "author"]
    list_filter = ["is_published", "published_at"]
    search_fields = ["title", "content"]
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ["author"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "published_at"

    def save_model(self, request, obj, form, change):
        # Stamp the publication time the first time a post is published so the
        # public queryset (published_at__lte=now) starts including it.
        if obj.is_published and obj.published_at is None:
            obj.published_at = timezone.now()
        # Default the author to the editing staff member on creation.
        if obj.author_id is None:
            obj.author = request.user
        super().save_model(request, obj, form, change)
