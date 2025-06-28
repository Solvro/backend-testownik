from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from users.views import admin_login


@extend_schema(exclude=True)
@api_view(["GET"])
@permission_classes([AllowAny])
def status(request):
    return Response({"status": "ok"})


@extend_schema(exclude=True)
@api_view(["GET"])
@permission_classes([AllowAny])
def root_redirect(request):
    return redirect("/swagger/")


urlpatterns = [
    # Root URL redirects to Swagger UI
    path("", root_redirect, name="index"),
    # Status
    path("status/", status, name="status"),
    # Admin
    path("admin/login/", admin_login, name="admin_login"),
    path("admin/", admin.site.urls),
    # Authentication
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # Docs
    path(
        "schema/",
        SpectacularAPIView.as_view(permission_classes=[AllowAny]),
        name="schema",
    ),
    path(
        "swagger/",
        SpectacularSwaggerView.as_view(
            url_name="schema", permission_classes=[AllowAny]
        ),
        name="swagger-ui",
    ),
    path(
        "redoc/",
        SpectacularRedocView.as_view(url_name="schema", permission_classes=[AllowAny]),
        name="redoc",
    ),
    # Include app routes
    path("", include("users.urls")),
    path("", include("quizzes.urls")),
    path("", include("grades.urls")),
    path("", include("feedback.urls")),
    path("", include("alerts.urls")),
]

# Admin site settings
admin.site.site_url = "https://testownik.solvro.pl/"
admin.site.site_header = "Testownik Solvro"
