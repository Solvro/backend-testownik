"""Shared authentication helpers for MCP toolsets."""

from rest_framework.exceptions import PermissionDenied


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
