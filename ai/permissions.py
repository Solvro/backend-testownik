from rest_framework.permissions import BasePermission


class HasAIStatsPermission(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.has_perm("ai.view_ai_usage_stats"))
        )


class CanManageAILimits(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.has_perm("ai.manage_ai_limits"))
        )
