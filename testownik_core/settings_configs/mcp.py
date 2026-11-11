DJANGO_MCP_ENDPOINT = "api/mcp/"
DJANGO_MCP_GLOBAL_SERVER_CONFIG = {
    "name": "testownik",
    "instructions": (
        "Testownik is a quiz and study platform. Tools act on behalf of the "
        "authenticated user and are limited by granted OAuth scopes. IDs are UUIDs. "
        "When creating quiz content, choose type single_choice, multiple_choice, true_false, or open; "
        "answers are marked by is_correct, with type-specific validation. "
        "AI-created content is labeled for user review. Tool errors are returned as "
        "objects with an 'error' field."
    ),
    "stateless": True,
}
DJANGO_MCP_AUTHENTICATION_CLASSES = [
    "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
]
