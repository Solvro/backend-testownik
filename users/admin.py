from django.contrib import admin
from django.contrib.auth.models import Group

from .models import EmailLoginToken, StudyGroup, Term, User, UserSettings


class UserSettingsInline(admin.StackedInline):
    model = UserSettings
    can_delete = False
    verbose_name_plural = "User settings"
    fk_name = "user"


class UserAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "first_name",
        "last_name",
        "student_number",
        "email",
        "is_staff",
        "is_superuser",
        "created_at",
        "updated_at",
    ]
    list_filter = [
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
        (None, {"fields": ("id", "email", "student_number", "usos_id")}),
        (
            "Personal info",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "sex",
                    "photo_url",
                    "overriden_photo_url",
                    "hide_profile",
                )
            },
        ),
        ("Status", {"fields": ("student_status", "staff_status")}),
        ("Permissions", {"fields": ("is_staff", "is_superuser")}),
    )
    readonly_fields = ["id", "created_at", "updated_at"]
    date_hierarchy = "created_at"

    inlines = (UserSettingsInline,)

    def has_add_permission(self, request, obj=None):
        return False


class StudyGroupAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "term"]
    list_filter = ["term"]
    search_fields = ["id", "name", "term__name"]
    filter_horizontal = ["members"]


class TermAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "start_date", "end_date", "finish_date"]
    list_filter = ["start_date", "end_date", "finish_date"]
    search_fields = ["id", "name"]
    date_hierarchy = "start_date"


class EmailLoginTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "created_at", "expires_at", "retry_count"]
    list_filter = ["created_at", "expires_at"]
    search_fields = [
        "user__first_name",
        "user__last_name",
        "user__email",
        "user__student_number",
    ]
    readonly_fields = ["created_at", "expires_at"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request, obj=None):
        return False


admin.site.register(User, UserAdmin)
admin.site.unregister(Group)
admin.site.register(StudyGroup, StudyGroupAdmin)
admin.site.register(Term, TermAdmin)
admin.site.register(EmailLoginToken, EmailLoginTokenAdmin)
