from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import (
    AdminLimitsResetView,
    AdminLimitsView,
    AdminModelViewSet,
    AdminPermissionsView,
    AdminSettingsView,
    AdminStatsView,
    AdminUserEventsView,
    AdminUserOverrideView,
    AdminUsersView,
    AvailableModelsView,
    ChatDetailView,
    ChatListView,
    InternalQuotaCheckView,
    InternalUsageReportView,
    MyUsageView,
)

router = SimpleRouter()
router.register("ai/usage/admin/models", AdminModelViewSet, basename="ai_admin_models")

urlpatterns = [
    path("ai/usage/check/", InternalQuotaCheckView.as_view(), name="ai_usage_check"),
    path("ai/usage/report/", InternalUsageReportView.as_view(), name="ai_usage_report"),
    path("ai/usage/me/", MyUsageView.as_view(), name="ai_usage_me"),
    path("ai/models/", AvailableModelsView.as_view(), name="ai_models"),
    path("ai/chats/", ChatListView.as_view(), name="ai_chat_list"),
    path("ai/chats/<uuid:conversation_id>/", ChatDetailView.as_view(), name="ai_chat_detail"),
    path("ai/usage/admin/limits/", AdminLimitsView.as_view(), name="ai_admin_limits"),
    path("ai/usage/admin/limits/reset/", AdminLimitsResetView.as_view(), name="ai_admin_limits_reset"),
    path("ai/usage/admin/permissions/", AdminPermissionsView.as_view(), name="ai_admin_permissions"),
    path("ai/usage/admin/stats/", AdminStatsView.as_view(), name="ai_admin_stats"),
    path("ai/usage/admin/users/", AdminUsersView.as_view(), name="ai_admin_users"),
    path("ai/usage/admin/users/<uuid:user_id>/limit/", AdminUserOverrideView.as_view(), name="ai_admin_user_limit"),
    path("ai/usage/admin/users/<uuid:user_id>/events/", AdminUserEventsView.as_view(), name="ai_admin_user_events"),
    path("ai/usage/admin/settings/", AdminSettingsView.as_view(), name="ai_admin_settings"),
    path("", include(router.urls)),
]
