from django.contrib import admin

from alerts.models import Alert


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ["title", "active", "color", "dismissible", "created_at", "updated_at"]
    list_filter = ["active", "color", "dismissible", "created_at", "updated_at"]
    search_fields = ["title", "content"]
    readonly_fields = ["id", "created_at", "updated_at"]
    fieldsets = (
        (None, {"fields": ("id", "active", "title", "content")}),
        ("Appearance", {"fields": ("dismissible", "color")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
    ordering = ["-created_at"]
    date_hierarchy = "created_at"
    actions = [
        "make_dismissible",
        "make_not_dismissible",
        "make_active",
        "make_inactive",
    ]

    def make_dismissible(self, request, queryset):
        queryset.update(dismissible=True)

    make_dismissible.short_description = "Mark selected alerts as dismissible"

    def make_not_dismissible(self, request, queryset):
        queryset.update(dismissible=False)

    make_not_dismissible.short_description = "Mark selected alerts as not dismissible"

    def make_active(self, request, queryset):
        queryset.update(active=True)

    make_active.short_description = "Mark selected alerts as active"

    def make_inactive(self, request, queryset):
        queryset.update(active=False)

    make_inactive.short_description = "Mark selected alerts as inactive"
