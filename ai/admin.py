from django.contrib import admin
from django.db.models import Count
from unfold.admin import ModelAdmin, StackedInline

from .models import (
    AIAccountLimit,
    AIChatConversation,
    AIChatMessage,
    AIModel,
    AIUsageDailyAggregate,
    AIUsageEvent,
    AIUsageSettings,
    AIUserLimitOverride,
)


class AIChatMessageInline(StackedInline):
    model = AIChatMessage
    extra = 0
    can_delete = False
    fields = (("order", "role", "model"), "message_id", "content", "created_at")
    readonly_fields = ("order", "role", "model", "message_id", "content", "created_at")
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AIChatConversation)
class AIChatConversationAdmin(ModelAdmin):
    list_display = ("conversation", "user", "scope", "quiz", "message_count", "created_at", "updated_at")
    list_filter = ("scope", "created_at", "updated_at")
    list_select_related = ("user", "quiz")
    search_fields = (
        "id",
        "title",
        "user__email",
        "user__first_name",
        "user__last_name",
        "quiz__title",
    )
    readonly_fields = tuple(field.name for field in AIChatConversation._meta.fields)
    date_hierarchy = "updated_at"
    show_full_result_count = False
    inlines = (AIChatMessageInline,)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(message_total=Count("messages"))

    @admin.display(description="Conversation", ordering="title")
    def conversation(self, obj):
        return obj.title or str(obj.id)

    @admin.display(description="Messages", ordering="message_total")
    def message_count(self, obj):
        return obj.message_total

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ConfiguredModelFilter(admin.SimpleListFilter):
    title = "model"
    parameter_name = "model"

    def lookups(self, request, model_admin):
        return AIModel.objects.order_by("model").values_list("model", "label")

    def queryset(self, request, queryset):
        return queryset.filter(model=self.value()) if self.value() else queryset


class ConfiguredProviderFilter(admin.SimpleListFilter):
    title = "provider"
    parameter_name = "provider"

    def lookups(self, request, model_admin):
        providers = AIModel.objects.order_by("provider").values_list("provider", flat=True).distinct()
        return ((provider, provider) for provider in providers)

    def queryset(self, request, queryset):
        return queryset.filter(model__provider=self.value()) if self.value() else queryset


@admin.register(AIUsageEvent)
class AIUsageEventAdmin(ModelAdmin):
    list_display = ("user", "scope", "model", "credits", "aborted", "created_at")
    list_filter = ("scope", ConfiguredModelFilter, ConfiguredProviderFilter, "aborted", "created_at")
    list_select_related = ("user", "model", "conversation", "quiz")
    show_full_result_count = False
    search_fields = ("user__email", "request_id", "conversation__id")
    readonly_fields = tuple(field.name for field in AIUsageEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AIAccountLimit, AIUserLimitOverride)
class AIConfigAdmin(ModelAdmin):
    pass


@admin.register(AIModel)
class AIModelAdmin(ModelAdmin):
    list_display = ("model", "label", "provider", "minimum_account_level", "active", "deleted_at", "updated_at")
    list_filter = ("provider", "minimum_account_level", "active", "deleted_at")
    search_fields = ("model", "label")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AIUsageSettings)
class AIUsageSettingsAdmin(ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AIUsageDailyAggregate)
class AIReadOnlyAdmin(ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
