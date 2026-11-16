"""Shared authentication helpers for MCP toolsets."""

from oauth2_provider.contrib.rest_framework import OAuth2Authentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied


class MCPOAuthAuthentication(OAuth2Authentication):
    """Keep OAuth token validation and reject unavailable account principals."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, _ = result
            if user is None or not user.is_active or user.is_banned:
                raise AuthenticationFailed("Account is unavailable.")
        return result


def require_scope(request, scope):
    """Check that an OAuth token carries the required scope.

    MCP tools are OAuth-only, so requests without an OAuth token scope are
    denied instead of being treated as first-party authenticated requests.
    """
    token = getattr(request, "auth", None)
    if token is None or not hasattr(token, "scope"):
        raise PermissionDenied("MCP tools require OAuth2 authentication.")
    scopes = (getattr(token, "scope", "") or "").split()
    if scope not in scopes:
        raise PermissionDenied(
            f"Token missing required scope: {scope}. Request a token with the '{scope}' scope to use this tool."
        )
