from django.contrib import admin
from django.contrib.auth.models import Group

from .models import StudyGroup, Term, User, UserSettings


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
    ]
    list_filter = ["is_staff", "is_superuser", "student_status", "staff_status"]

    fieldsets = (
        (None, {"fields": ("id", "email", "student_number")}),
        (
            "Personal info",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "sex",
                    "photo_url",
                    "overriden_photo_url",
                )
            },
        ),
        ("Status", {"fields": ("student_status", "staff_status")}),
        ("Permissions", {"fields": ("is_staff", "is_superuser")}),
    )
    readonly_fields = ["id"]

    inlines = (UserSettingsInline,)

    def has_add_permission(self, request, obj=None):
        return False


class StudyGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "term"]
    list_filter = ["term"]
    search_fields = ["name"]


class TermAdmin(admin.ModelAdmin):
    list_display = ["name", "start_date", "end_date"]
    list_filter = ["start_date", "end_date"]
    search_fields = ["name"]


admin.site.register(User, UserAdmin)
admin.site.unregister(Group)
admin.site.register(StudyGroup, StudyGroupAdmin)
admin.site.register(Term, TermAdmin)
