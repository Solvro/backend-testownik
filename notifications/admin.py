from django.contrib import admin

from .models import Notification


class NotificationAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "notification_type", "delivery_status", "is_read", "created_at"]
    list_filter = ["notification_type", "delivery_status", "is_read", "created_at"]
    search_fields = ["title", "content", "user__first_name", "user__last_name", "user__email"]
    autocomplete_fields = ["user"]
    readonly_fields = ["id", "delivery_status", "delivery_error", "created_at", "updated_at"]
    date_hierarchy = "created_at"


admin.site.register(Notification, NotificationAdmin)
