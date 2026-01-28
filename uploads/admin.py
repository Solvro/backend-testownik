from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import UploadedImage


@admin.register(UploadedImage)
class UploadedImageAdmin(admin.ModelAdmin):
    """Admin interface for managing uploaded images."""

    list_display = [
        "id",
        "thumbnail_preview",
        "original_filename",
        "dimensions",
        "file_size_display",
        "uploaded_by",
        "uploaded_at",
        "reference_count",
    ]
    list_filter = ["uploaded_at", "content_type"]
    search_fields = ["id", "original_filename", "uploaded_by__email"]
    readonly_fields = [
        "id",
        "image_preview",
        "original_filename",
        "content_type",
        "file_size",
        "width",
        "height",
        "uploaded_by",
        "uploaded_at",
    ]
    ordering = ["-uploaded_at"]
    date_hierarchy = "uploaded_at"

    def get_queryset(self, request):
        """Annotate queryset with reference counts to avoid unnecessary queries."""
        qs = super().get_queryset(request)
        return qs.annotate(
            _question_count=Count("questions", distinct=True),
            _answer_count=Count("answers", distinct=True),
        )

    def thumbnail_preview(self, obj):
        """Display small thumbnail in list view."""
        if obj.image:
            try:
                return format_html(
                    '<img src="{}" style="max-height: 50px; max-width: 80px; object-fit: contain;" />', obj.image.url
                )
            except Exception:
                return mark_safe('<span style="color: #c00;">File missing</span>')
        return "-"

    thumbnail_preview.short_description = "Preview"

    def image_preview(self, obj):
        """Display larger image preview in detail view."""
        if obj.image:
            try:
                return format_html('<img src="{}" style="max-height: 300px; max-width: 500px;" />', obj.image.url)
            except Exception:
                return mark_safe('<span style="color: #c00;">File missing from storage</span>')
        return "-"

    image_preview.short_description = "Image Preview"

    def dimensions(self, obj):
        """Display image dimensions."""
        if obj.width and obj.height:
            return f"{obj.width}×{obj.height}"
        return "-"

    dimensions.short_description = "Size (px)"

    def file_size_display(self, obj):
        """Display human-readable file size."""
        if obj.file_size:
            if obj.file_size < 1024:
                return f"{obj.file_size} B"
            elif obj.file_size < 1024 * 1024:
                return f"{obj.file_size / 1024:.1f} KB"
            else:
                return f"{obj.file_size / (1024 * 1024):.2f} MB"
        return "-"

    file_size_display.short_description = "File Size"
    file_size_display.admin_order_field = "file_size"

    def reference_count(self, obj):
        """Count how many questions/answers reference this image."""
        count = obj._question_count + obj._answer_count
        if count == 0:
            return mark_safe('<span style="color: #999;">0 (orphan)</span>')
        return count

    reference_count.short_description = "References"
