from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.utils.module_loading import import_string
from django.views.generic import TemplateView
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from mcp_server.views import MCPServerStreamableHttpView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from oauth_integrations.views import (
    AuthorizationRequestAPIView,
    AuthorizationServerMetadataView,
    AuthorizedAppsViewSet,
    ProtectedResourceMetadataView,
)
from testownik_core.views import ApiIndexView
from users.views import (
    CustomTokenObtainPairView,
    CustomTokenRefreshView,
    admin_login,
)


@extend_schema(exclude=True)
@api_view(["GET"])
@permission_classes([AllowAny])
def status(request):
    return Response({"status": "ok"})


MCPServerStreamableHttpView.__doc__ = """Endpoint for MCP server communication. 
Supports streaming responses and is designed to handle long-lived connections for real-time interactions. 
This endpoint is used by the MCP server to manage sessions and facilitate communication between clients and the server.
"""


mcp_view = MCPServerStreamableHttpView.as_view(
    permission_classes=([IsAuthenticated] if getattr(settings, "DJANGO_MCP_AUTHENTICATION_CLASSES", None) else []),
    authentication_classes=[import_string(cls) for cls in getattr(settings, "DJANGO_MCP_AUTHENTICATION_CLASSES", [])],
)

base_urlpatterns = [
    path("", ApiIndexView.as_view(), name="api_index"),
    path(
        "scalar/",
        TemplateView.as_view(template_name="scalar.html"),
        name="scalar-ui",
    ),
    # Status
    path("status/", status, name="status"),
    # Admin
    path("admin/login/", admin_login, name="admin_login"),
    path("admin/", admin.site.urls),
    # Authentication
    path("token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", CustomTokenRefreshView.as_view(), name="token_refresh"),
    # Docs
    path(
        "schema/",
        SpectacularAPIView.as_view(permission_classes=[AllowAny]),
        name="schema",
    ),
    path(
        "swagger/",
        SpectacularSwaggerView.as_view(url_name="schema", permission_classes=[AllowAny]),
        name="swagger-ui",
    ),
    path(
        "redoc/",
        SpectacularRedocView.as_view(url_name="schema", permission_classes=[AllowAny]),
        name="redoc",
    ),
    re_path(
        r"^mcp/?$",
        mcp_view,
        name="mcp_server_streamable_http_endpoint",
    ),
    # Include app routes
    path("", include("users.urls")),
    path("", include("quizzes.urls")),
    path("", include("grades.urls")),
    path("", include("wrapped.urls")),
    path("", include("feedback.urls")),
    path("", include("uploads.urls")),
    # OAuth 2.0
    path("oauth/authorize/request/", AuthorizationRequestAPIView.as_view(), name="oauth_authorize_request"),
    path("oauth/", include("oauth2_provider.urls", namespace="oauth2_provider")),
    path("oauth/authorized-apps/", AuthorizedAppsViewSet.as_view({"get": "list"}), name="authorized_apps"),
    path(
        "oauth/authorized-apps/<path:client_id>/",
        AuthorizedAppsViewSet.as_view({"delete": "destroy"}),
        name="authorized_app_detail",
    ),
    path("", include("notifications.urls")),
]

urlpatterns = [
    path("api/", include(base_urlpatterns)),
    path("", ApiIndexView.as_view(), name="index"),
    path(
        ".well-known/oauth-authorization-server",
        AuthorizationServerMetadataView.as_view(),
        name="oauth_authorization_server_metadata",
    ),
    path(
        ".well-known/oauth-protected-resource",
        ProtectedResourceMetadataView.as_view(),
        name="oauth_protected_resource_metadata",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
