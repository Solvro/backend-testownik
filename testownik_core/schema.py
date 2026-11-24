"""OpenAPI schema tagging: one tag per area of the API instead of a single `api` tag."""

import re

from drf_spectacular.openapi import AutoSchema as BaseAutoSchema

# First path segment after `/api/` -> tag. `extend_schema(tags=...)` on a view still wins.
PATH_SEGMENT_TAGS = {
    "ai": "AI",
    "authorize": "Authentication",
    "generate-otp": "Authentication",
    "guest": "Authentication",
    "login": "Authentication",
    "login-link": "Authentication",
    "login-otp": "Authentication",
    "token": "Authentication",
    "blog": "Blog",
    "comments": "Comments",
    "feedback": "Feedback",
    "grades": "Grades",
    "legal": "Legal",
    "folders": "Library",
    "library": "Library",
    "mcp": "MCP",
    "notifications": "Notifications",
    "oauth": "OAuth",
    "questions": "Questions",
    "random-question": "Questions",
    "report-question-issue": "Questions",
    "quiz-ratings": "Ratings",
    "last-used-quizzes": "Quizzes",
    "quizzes": "Quizzes",
    "search-quizzes": "Quizzes",
    "shared-quizzes": "Sharing",
    "study-groups": "Sharing",
    "upload": "Uploads",
    "settings": "Users",
    "user": "Users",
    "users": "Users",
    "wrapped": "Wrapped",
}

API_PATH_SEGMENT = re.compile(r"^/api/([^/{]+)")


class AutoSchema(BaseAutoSchema):
    def get_tags(self) -> list[str]:
        match = API_PATH_SEGMENT.match(self.path)
        if match is None:
            # Paths outside `/api/` keep their first segment, e.g. `.well-known`.
            return super().get_tags()
        segment = match.group(1)
        return [PATH_SEGMENT_TAGS.get(segment, segment)]
