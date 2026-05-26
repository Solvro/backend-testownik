from django.contrib import admin
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin, StackedInline

from .models import EmailLoginToken, StudyGroup, Term, User, UserSettings


class UserSettingsInline(StackedInline):
    model = UserSettings
    can_delete = False
    verbose_name_plural = "User settings"
    fk_name = "user"


@admin.register(User)
class UserAdmin(ModelAdmin):
    list_display = [
        "id",
        "first_name",
        "last_name",
        "student_number",
        "email",
        "account_type",
        "account_level",
        "is_banned",
        "is_staff",
        "is_superuser",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "account_type",
        "account_level",
        "is_banned",
        "is_staff",
        "is_superuser",
        "student_status",
        "staff_status",
        "sex",
        "hide_profile",
        "created_at",
        "updated_at",
    ]
    search_fields = ["first_name", "last_name", "student_number", "email", "usos_id"]

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "email",
                    "account_type",
                    "account_level",
                    "student_number",
                    "usos_id",
                )
            },
        ),
        (
            "Personal info",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "sex",
                    "photo_image",
                    "custom_photo_image",
                    "hide_profile",
                )
            },
        ),
        ("Status", {"fields": ("student_status", "staff_status")}),
        ("Permissions", {"fields": ("is_staff", "is_superuser")}),
        (
            "Ban Status",
            {
                "fields": ("is_banned", "ban_reason"),
                "description": "Ban a user to prevent them from using the platform.",
            },
        ),
    )
    readonly_fields = ["id", "created_at", "updated_at"]
    date_hierarchy = "created_at"

    inlines = (UserSettingsInline,)
    actions = ["ban_users", "unban_users"]

    def has_add_permission(self, request, obj=None):
        return False

    @admin.action(description="Ban selected users")
    def ban_users(self, request, queryset):
        count = queryset.update(is_banned=True)
        self.message_user(request, f"Successfully banned {count} user(s).")

    @admin.action(description="Unban selected users")
    def unban_users(self, request, queryset):
        count = queryset.update(is_banned=False, ban_reason=None)
        self.message_user(request, f"Successfully unbanned {count} user(s).")


@admin.register(StudyGroup)
class StudyGroupAdmin(ModelAdmin):
    list_display = ["id", "name", "term"]
    list_filter = ["term"]
    search_fields = ["id", "name", "term__name"]
    filter_horizontal = ["members"]


@admin.register(Term)
class TermAdmin(ModelAdmin):
    list_display = ["id", "name", "start_date", "end_date", "finish_date"]
    list_filter = ["start_date", "end_date", "finish_date"]
    search_fields = ["id", "name"]
    date_hierarchy = "start_date"


@admin.register(EmailLoginToken)
class EmailLoginTokenAdmin(ModelAdmin):
    list_display = ["user", "created_at", "expires_at", "retry_count"]
    list_filter = ["created_at", "expires_at"]
    search_fields = [
        "user__first_name",
        "user__last_name",
        "user__email",
        "user__student_number",
    ]
    readonly_fields = ["created_at"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request, obj=None):
        return False


admin.site.unregister(Group)
