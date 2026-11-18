import contextlib

from django import forms
from django.contrib import admin
from django.contrib.admin import helpers
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth.models import Group
from django.template.response import TemplateResponse
from oauth2_provider.admin import AccessTokenAdmin as BaseAccessTokenAdmin
from oauth2_provider.admin import ApplicationAdmin as BaseApplicationAdmin
from oauth2_provider.admin import GrantAdmin as BaseGrantAdmin
from oauth2_provider.admin import IDTokenAdmin as BaseIDTokenAdmin
from oauth2_provider.admin import RefreshTokenAdmin as BaseRefreshTokenAdmin
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_grant_model,
    get_id_token_model,
    get_refresh_token_model,
)
from rest_framework_simplejwt.token_blacklist.admin import (
    BlacklistedTokenAdmin as BaseBlacklistedTokenAdmin,
)
from rest_framework_simplejwt.token_blacklist.admin import (
    OutstandingTokenAdmin as BaseOutstandingTokenAdmin,
)
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.widgets import UnfoldAdminTextareaWidget

from oauth_integrations.models import OAuthApplicationMetadata

from .models import (
    CourseClassType,
    EmailLoginToken,
    Faculty,
    StudentProgramme,
    StudyGroup,
    StudyProgramme,
    Term,
    User,
    UserSettings,
)


class UserSettingsInline(StackedInline):
    model = UserSettings
    can_delete = False
    verbose_name_plural = "User settings"
    fk_name = "user"


class StudentProgrammeInline(TabularInline):
    model = StudentProgramme
    extra = 0
    can_delete = False
    fields = ["programme", "semester", "is_primary"]
    readonly_fields = fields
    verbose_name_plural = "Studies (from USOS)"

    def has_add_permission(self, request, obj=None):
        return False


class UserAdminForm(forms.ModelForm):
    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("is_banned") and not (cleaned_data.get("ban_reason") or "").strip():
            self.add_error("ban_reason", "A banned user must be told why.")
        return cleaned_data


class BanUsersForm(forms.Form):
    reason = forms.CharField(
        label="Reason",
        help_text="Shown to the banned users when they try to log in.",
        widget=UnfoldAdminTextareaWidget(attrs={"rows": 4}),
    )


@admin.register(User)
class UserAdmin(ModelAdmin):
    form = UserAdminForm
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
        "student_programmes__programme__faculty",
        "student_programmes__semester",
        "sex",
        "hide_profile",
        "created_at",
        "updated_at",
    ]
    search_fields = ["first_name", "last_name", "student_number", "email", "usos_id"]
    autocomplete_fields = ["photo_image", "custom_photo_image"]

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
                    "photo_url",
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
    readonly_fields = ["id", "photo_url", "created_at", "updated_at"]
    date_hierarchy = "created_at"

    inlines = (StudentProgrammeInline, UserSettingsInline)
    actions = ["ban_users", "unban_users"]

    def has_add_permission(self, request, obj=None):
        return False

    @admin.action(description="Ban selected users")
    def ban_users(self, request, queryset):
        form = BanUsersForm(request.POST if "apply" in request.POST else None)
        if form.is_valid():
            count = queryset.update(is_banned=True, ban_reason=form.cleaned_data["reason"])
            self.message_user(request, f"Successfully banned {count} user(s).")
            return None
        return TemplateResponse(
            request,
            "admin/users/user/ban_users.html",
            {
                **self.admin_site.each_context(request),
                "title": "Ban selected users",
                "opts": self.model._meta,
                "form": form,
                "user_count": queryset.count(),
                "selected_ids": request.POST.getlist(helpers.ACTION_CHECKBOX_NAME),
                "select_across": request.POST.get("select_across", "0"),
                "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            },
        )

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


@admin.register(Faculty)
class FacultyAdmin(ModelAdmin):
    list_display = ["id", "name"]
    search_fields = ["id", "name"]


@admin.register(StudyProgramme)
class StudyProgrammeAdmin(ModelAdmin):
    list_display = ["id", "name", "faculty"]
    list_filter = ["faculty"]
    list_select_related = ["faculty"]
    search_fields = ["id", "name", "faculty__name"]


@admin.register(CourseClassType)
class CourseClassTypeAdmin(ModelAdmin):
    list_display = ["id", "name_pl", "name_en", "synced_at"]
    search_fields = ["id", "name_pl", "name_en"]
    readonly_fields = ["synced_at"]


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


# Re-register django-oauth-toolkit models with Unfold's ModelAdmin styling.
Application = get_application_model()
AccessToken = get_access_token_model()
Grant = get_grant_model()
RefreshToken = get_refresh_token_model()
IDToken = get_id_token_model()


for model in (Application, AccessToken, Grant, RefreshToken, IDToken):
    with contextlib.suppress(NotRegistered):
        admin.site.unregister(model)


@admin.register(Application)
class ApplicationAdmin(BaseApplicationAdmin, ModelAdmin):
    class OAuthApplicationMetadataInline(StackedInline):
        model = OAuthApplicationMetadata
        can_delete = True
        extra = 0
        max_num = 1
        verbose_name_plural = "Testownik metadata"

    inlines = [OAuthApplicationMetadataInline]


@admin.register(AccessToken)
class AccessTokenAdmin(BaseAccessTokenAdmin, ModelAdmin):
    pass


@admin.register(Grant)
class GrantAdmin(BaseGrantAdmin, ModelAdmin):
    pass


@admin.register(RefreshToken)
class RefreshTokenAdmin(BaseRefreshTokenAdmin, ModelAdmin):
    pass


@admin.register(IDToken)
class IDTokenAdmin(BaseIDTokenAdmin, ModelAdmin):
    pass


# Re-register Simple JWT token blacklist models with Unfold's ModelAdmin styling.
for model in (OutstandingToken, BlacklistedToken):
    with contextlib.suppress(NotRegistered):
        admin.site.unregister(model)


@admin.register(OutstandingToken)
class OutstandingTokenAdmin(BaseOutstandingTokenAdmin, ModelAdmin):
    pass


@admin.register(BlacklistedToken)
class BlacklistedTokenAdmin(BaseBlacklistedTokenAdmin, ModelAdmin):
    autocomplete_fields = ["token"]
