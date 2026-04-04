from django.conf import settings
from rest_framework import permissions

from users.models import AccountType

from .models import Question, Quiz


def _is_effectively_authenticated(user) -> bool:
    """
    Returns True if the user is authenticated AND not a guest.
    Guest users are treated as unauthenticated for permission purposes
    (they cannot access shared quizzes, shared groups, etc.).
    """
    return user.is_authenticated and getattr(user, "account_type", None) != AccountType.GUEST


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


class IsSharedQuizCreatorOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow creator of a shared quiz to edit it.
    Also enforces account-type restrictions:
    - Guests cannot view or share quizzes
    - Only Email, Student, and Lecturer accounts can view shared quizzes
    - Only Email, Student, and Lecturer accounts can share quizzes
    """

    CAN_VIEW_SHARED = {AccountType.EMAIL, AccountType.STUDENT, AccountType.LECTURER}
    CAN_SHARE = {AccountType.EMAIL, AccountType.STUDENT, AccountType.LECTURER}

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        account_type = getattr(request.user, "account_type", None)

        if request.method in permissions.SAFE_METHODS:
            return account_type in self.CAN_VIEW_SHARED

        return account_type in self.CAN_SHARE

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True

        return obj.quiz.folder.owner == request.user


class IsQuizCreator(permissions.BasePermission):
    """
    Custom permission for critical actions like Move or Delete.
    Only the folder owner can perform these actions.
    """

    def has_object_permission(self, request, view, obj):
        return obj.folder.owner == request.user


class IsQuizReadable(permissions.BasePermission):
    """
    Custom permission for read access to a quiz.
    Allowed if:
    - User is the folder owner
    - Quiz is public or unlisted (visibility >= 2) and user is authenticated (or quiz allows anonymous)
    - Quiz is shared with the user explicitly (requires non-guest account)
    - Quiz is shared with a group the user belongs to (requires non-guest account)

    Guest users are treated as unauthenticated for shared quiz access.
    """

    def has_object_permission(self, request, view, obj: Quiz):
        if obj.folder.owner == request.user:
            return True

        if obj.visibility >= 2 and (request.user.is_authenticated or obj.allow_anonymous):
            return True

        if _is_effectively_authenticated(request.user) and obj.sharedquiz_set.filter(user=request.user).exists():
            return True

        return (
            _is_effectively_authenticated(request.user)
            and obj.sharedquiz_set.filter(study_group__in=request.user.study_groups.all()).exists()
        )


class IsQuestionReadable(permissions.BasePermission):
    """
    Forwards the request to IsQuizReadable for the quiz.
    """

    def has_object_permission(self, request, view, obj: Question):
        return IsQuizReadable().has_object_permission(request, view, obj.quiz)


class IsQuizCreatorOrCollaboratorOrReadOnly(permissions.BasePermission):
    """
    Custom permission to allow quiz creator and accepted collaborators to edit the quiz.
    """

    def has_object_permission(self, request, view, obj: Quiz | Question):
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the creator or accepted collaborators
        if isinstance(obj, Quiz):
            return obj.can_edit(request.user)

        if isinstance(obj, Question):
            return obj.quiz.can_edit(request.user)

        return False


class IsFolderOwner(permissions.BasePermission):
    """
    Custom permission to only allow folder owners to edit.
    """

    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user
