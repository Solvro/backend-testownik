from django.contrib import admin
from django.contrib.auth.models import Group

from .models import StudyGroup, User, UserSettings


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

    fieldsets = (
        (None, {"fields": ("id", "email", "student_number")}),
        ("Personal info", {"fields": ("first_name", "last_name", "sex", "photo_url")}),
        ("Status", {"fields": ("student_status", "staff_status")}),
        ("Permissions", {"fields": ("is_staff", "is_superuser")}),
    )
    readonly_fields = ["id"]

    inlines = (UserSettingsInline,)

    def has_add_permission(self, request, obj=None):
        return False


admin.site.register(User, UserAdmin)
admin.site.unregister(Group)
admin.site.register(StudyGroup)
