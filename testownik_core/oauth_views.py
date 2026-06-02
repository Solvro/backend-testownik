from django.conf import settings
from oauth2_provider.models import AccessToken, RefreshToken
from oauth2_provider.views import AuthorizationView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class ScopedAuthorizationView(AuthorizationView):
    """Consent screen that lets the user approve a subset of requested scopes.

    The default django-oauth-toolkit view renders the requested scopes as static
    text and grants all of them. We expose each scope as an individual checkbox;
    the template collects the checked scopes into the form's ``scope`` field, so
    the issued token only carries the scopes the user actually approved.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        scopes = context.get("scopes", []) or []
        descriptions = context.get("scopes_descriptions", []) or []
        context["scopes_zip"] = list(zip(scopes, descriptions))
        return context


class AuthorizationServerMetadataView(APIView):
    """RFC 8414 — OAuth 2.0 Authorization Server Metadata."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        issuer = settings.SITE_URL
        return Response(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/api/oauth/authorize/",
                "token_endpoint": f"{issuer}/api/oauth/token/",
                "registration_endpoint": f"{issuer}/api/oauth/register/",
                "revocation_endpoint": f"{issuer}/api/oauth/revoke_token/",
                "introspection_endpoint": f"{issuer}/api/oauth/introspect/",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": list(settings.OAUTH2_PROVIDER["SCOPES"].keys()),
                "token_endpoint_auth_methods_supported": [
                    "none",
                    "client_secret_basic",
                    "client_secret_post",
                ],
            }
        )


class ProtectedResourceMetadataView(APIView):
    """RFC 9728 — OAuth 2.0 Protected Resource Metadata."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        site_url = settings.SITE_URL
        mcp_endpoint = settings.DJANGO_MCP_ENDPOINT.strip("/")
        return Response(
            {
                "resource": f"{site_url}/{mcp_endpoint}",
                "authorization_servers": [site_url],
                "scopes_supported": list(settings.OAUTH2_PROVIDER["SCOPES"].keys()),
            }
        )


class AuthorizedAppsView(APIView):
    """Manage OAuth apps authorized by the current user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tokens = AccessToken.objects.filter(user=request.user).select_related("application").order_by("-created")
        seen = set()
        apps = []
        for token in tokens:
            app = token.application
            if app is None or app.client_id in seen:
                continue
            seen.add(app.client_id)
            apps.append(
                {
                    "client_id": app.client_id,
                    "client_name": app.name,
                    "created": token.created,
                    "scopes": token.scope,
                }
            )
        return Response(apps)

    def delete(self, request, client_id=None):
        if not client_id:
            return Response({"error": "client_id is required"}, status=400)
        refresh_deleted, _ = RefreshToken.objects.filter(
            user=request.user,
            application__client_id=client_id,
        ).delete()
        access_deleted, _ = AccessToken.objects.filter(
            user=request.user,
            application__client_id=client_id,
        ).delete()
        if refresh_deleted == 0 and access_deleted == 0:
            return Response({"error": "No tokens found for this app"}, status=404)
        return Response(status=204)
