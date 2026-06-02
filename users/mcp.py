from mcp_server import MCPToolset

from testownik_core.mcp_auth import require_scope as _require_scope
from users.models import UserSettings


class UserTools(MCPToolset):
    def get_my_profile(self) -> dict:
        """Return the current user's profile information like name and email"""
        _require_scope(self.request, "user:read")
        user = self.request.user
        return {
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": user.full_name
        }

    def get_my_settings(self) -> dict:
        """Return the current user's quiz and notification settings, including
        reoccurrence config, AI preferences, and notification toggles."""
        _require_scope(self.request, "user:read")
        user = self.request.user
        settings, _ = UserSettings.objects.get_or_create(user=user)
        return {
            "sync_progress": settings.sync_progress,
            "initial_reoccurrences": settings.initial_reoccurrences,
            "wrong_answer_reoccurrences": settings.wrong_answer_reoccurrences,
            "max_question_reoccurrences": settings.max_question_reoccurrences,
            "ai_disabled": settings.ai_disabled,
            "notify_quiz_shared": settings.notify_quiz_shared,
            "notify_bug_reported": settings.notify_bug_reported,
            "notify_marketing": settings.notify_marketing,
        }
