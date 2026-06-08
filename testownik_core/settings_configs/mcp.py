DJANGO_MCP_ENDPOINT = "api/mcp/"
DJANGO_MCP_GLOBAL_SERVER_CONFIG = {
    "name": "testownik",
    "instructions": (
        "Testownik is a quiz and study platform. Tools act on behalf of the "
        "authenticated user and are limited by granted OAuth scopes. IDs are UUIDs. "
        "When creating quiz content, use normal questions with at least one answers, preferably more like 4; "
        "answers are marked by is_correct and multiple correct answers are allowed. "
        "AI-created content is labeled for user review. Tool errors are returned as "
        "objects with an 'error' field."
    ),
    "stateless": True,
}
DJANGO_MCP_AUTHENTICATION_CLASSES = [
    "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
]
