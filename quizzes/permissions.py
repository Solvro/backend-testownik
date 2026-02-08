from django.conf import settings
from rest_framework import permissions

from .models import Quiz


class IsInternalApiRequest(permissions.BasePermission):
    """
    Permission class that validates Api-Key header against INTERNAL_API_KEY.
    Used for server-to-server authentication (e.g., Next.js server-side).
    """

    def has_permission(self, request, view):
        api_key = request.headers.get("Api-Key")
        if not api_key or not settings.INTERNAL_API_KEY:
            return False
        return api_key == settings.INTERNAL_API_KEY


class IsSharedQuizMaintainerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow maintainer of a shared quiz to edit it.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the maintainer of the shared quiz.
        return obj.quiz.maintainer == request.user


class IsQuizMaintainer(permissions.BasePermission):
    """
    Custom permission for critical actions like Move or Delete.
    Blocks collaborators - only the quiz maintainer can perform these actions.
    """

    def has_object_permission(self, request, view, obj):
        return obj.maintainer == request.user


class IsQuizReadable(permissions.BasePermission):
    """
    Custom permission for read access to a quiz.
    Allowed if:
    - User is the maintainer
    - Quiz is public or unlisted (visibility >= 2)
    - Quiz is shared with the user explicitly
    - Quiz is shared with a group the user belongs to

    If the user is not authenticated:
    - Anonymous access is allowed for the quiz and visibility >= 2
    """

    def has_object_permission(self, request, view, obj: Quiz):
        if obj.maintainer == request.user:
            return True

        if obj.visibility >= 2 and (request.user.is_authenticated or obj.allow_anonymous):
            return True

        if request.user.is_authenticated and obj.sharedquiz_set.filter(user=request.user).exists():
            return True

        return (
            request.user.is_authenticated
            and obj.sharedquiz_set.filter(study_group__in=request.user.study_groups.all()).exists()
        )


class IsQuizMaintainerOrCollaborator(permissions.BasePermission):
    """
    Custom permission to allow quiz maintainers and accepted collaborators to edit the quiz while
    maintaining read access to IsQuizReadable logic.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are delegated to IsQuizReadable logic
        if request.method in permissions.SAFE_METHODS:
            return IsQuizReadable().has_object_permission(request, view, obj)

        # Write permissions are only allowed to the maintainer or accepted collaborators
        return obj.can_edit(request.user)


class IsFolderOwner(permissions.BasePermission):
    """
    Custom permission to only allow folder owners to edit.
    """

    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user
