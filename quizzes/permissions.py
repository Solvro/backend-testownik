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


class IsQuizMaintainer(permissions.BasePermission):
    """
    Custom permission for critical actions like Move or Delete.
    Blocks collaborators - only the quiz maintainer can perform these actions.
    """

    def has_object_permission(self, request, view, obj):
        return obj.maintainer == request.user


class IsQuizMaintainerOrCollaborator(permissions.BasePermission):
    """
    Custom permission to allow quiz maintainers and accepted collaborators to edit the quiz.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the maintainer or accepted collaborators
        return obj.can_edit(request.user)


class IsFolderOwner(permissions.BasePermission):
    """
    Custom permission to only allow folder owners to edit.
    """

    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user
