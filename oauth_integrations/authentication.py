"""Scoped OAuth access to the existing REST API, alongside browser JWT sessions."""

from oauth2_provider.contrib.rest_framework import OAuth2Authentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

# An explicit allowlist keeps newly added/admin views closed to third-party clients.
RESOURCE_VIEWS = {
    "quizzes.views": {
        "QuizViewSet": "quizzes",
        "SharedQuizViewSet": "quizzes",
        "QuizShortcutViewSet": "quizzes",
        "FolderViewSet": "quizzes",
        "QuestionViewSet": "quizzes",
        "QuizRatingViewSet": "quizzes",
        "CommentViewSet": "quizzes",
        "LibraryView": "quizzes",
        "SearchQuizzesView": "quizzes",
        "LastUsedQuizzesView": "quizzes",
        "RandomQuestionView": "quizzes",
        "ReportQuestionIssueView": "quizzes",
    },
    "users.views.user_management": {
        "CurrentUserView": "user",
        "SettingsViewSet": "user",
        "UserPhotoView": "user",
        "UserViewSet": "user",
        "StudyGroupViewSet": "user",
    },
    "notifications.views": {"NotificationViewSet": "notifications"},
    "uploads.views": {"ImageUploadView": "quizzes"},
    "feedback.views": {"FeedbackAddView": "feedback"},
    "ai.views": {"MyUsageView": "ai", "AvailableModelsView": "ai", "ChatListView": "ai", "ChatDetailView": "ai"},
    "oauth_integrations.views": {"AuthorizedAppsViewSet": "user", "OAuthIdentityView": "ai"},
    "mobile_api.views": {
        "MobileAnswerView": "study",
        "MobileWebSessionView": "web",
        # The view itself also requires the first-party mobile client.
        "MobileAccountDeletionView": "user",
    },
    "mobile_api.quiz_create": {"MobileQuizCreateView": "quizzes"},
}


def required_oauth_scope(request):
    view = request.parser_context.get("view")
    cls = type(view)
    module, name = cls.__module__, cls.__name__
    resource = RESOURCE_VIEWS.get(module, {}).get(name)
    # Grades and Wrapped expose only read endpoints; mutations are never inferred.
    if module.startswith("grades.views") and request.method in {"GET", "HEAD", "OPTIONS"}:
        return "grades:read"
    if module.startswith("wrapped.views") and request.method in {"GET", "HEAD", "OPTIONS"}:
        return "study:read"
    if name == "QuizViewSet" and module == "quizzes.views":
        action = request.resolver_match.func.actions.get(request.method.lower(), "")
        if action == "progress" or action == "record_answer" or action.startswith("stats"):
            resource = "study"
    if resource is None:
        return None
    if name == "OAuthIdentityView":
        return "ai:write"
    if name == "MobileWebSessionView":
        return "web:read"
    return f"{resource}:{'read' if request.method in {'GET', 'HEAD', 'OPTIONS'} else 'write'}"


class APIBearerAuthentication(JWTAuthentication):
    """Reject insufficient OAuth scopes even on views with custom permission classes."""

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None
        raw = self.get_raw_token(header)
        if raw is None:
            return None
        if raw.count(b".") == 2:
            result = super().authenticate(request)
            if result and result[1].get("mobile_embed"):
                scope = required_oauth_scope(request)
                if request.method not in {"GET", "HEAD", "OPTIONS"} or scope not in {
                    "study:read",
                    "quizzes:read",
                    "user:read",
                }:
                    raise PermissionDenied("Embedded sessions are read-only.")
            return result
        result = OAuth2Authentication().authenticate(request)
        if result is None:
            raise AuthenticationFailed("Invalid or expired OAuth access token.")
        user, token = result
        if not user.is_active or user.is_banned:
            raise AuthenticationFailed("Account is unavailable.")
        scope = required_oauth_scope(request)
        if scope is None or not token.allow_scopes([scope]):
            raise PermissionDenied("The OAuth grant does not allow this operation.")
        return result
