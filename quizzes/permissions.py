from rest_framework import permissions


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
