from rest_framework.permissions import BasePermission


class CanManageAccountLevels(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.has_perm("users.manage_account_levels") or request.user.is_superuser)
        )
