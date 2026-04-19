from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from users.auth_cookies import set_jwt_cookies
from users.serializers import UserTokenObtainPairSerializer, UserTokenRefreshSerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    """Custom token obtain view that includes user data in the access token."""

    serializer_class = UserTokenObtainPairSerializer

    @extend_schema(
        summary="Obtain JWT token pair",
        description=(
            "Authenticate with email and password. "
            "On success, both tokens are set as cookies and the JSON body returns a confirmation message. "
            "The `access_token` cookie is readable by client JavaScript, while `refresh_token` is HTTP-only. "
            "The `access` token contains embedded user data "
            "(first_name, last_name, email, student_number, photo, account_type, etc.)."
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "format": "email"},
                    "password": {"type": "string"},
                },
                "required": ["email", "password"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
            },
            401: OpenApiResponse(description="No active account found with the given credentials."),
            404: OpenApiResponse(description="Not found."),
        },
        examples=[
            OpenApiExample(
                "Valid request",
                value={"email": "user@example.com", "password": "securepassword"},
            ),
            OpenApiExample(
                "Success response",
                response_only=True,
                value={"message": "Login successful"},
            ),
        ],
        tags=["Authentication"],
    )
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            set_jwt_cookies(
                response,
                response.data.get("access"),
                response.data.get("refresh"),
            )
            response.data = {"message": "Login successful"}
        return response


class CustomTokenRefreshView(TokenRefreshView):
    """Custom token refresh view that re-populates user data in the access token."""

    serializer_class = UserTokenRefreshSerializer

    @extend_schema(
        summary="Refresh JWT token",
        description=(
            "Exchange a valid `refresh` token for a new `access`/`refresh` pair. "
            "On success, new tokens are set as cookies and the JSON body returns a confirmation message. "
            "The `access_token` cookie is readable by client JavaScript, while `refresh_token` is HTTP-only. "
            "The new `access` token contains re-populated user data."
        ),
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "refresh": {"type": "string"},
                },
                "required": ["refresh"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
            },
            401: OpenApiResponse(description="Invalid or expired refresh token."),
            404: OpenApiResponse(description="Not found."),
        },
        examples=[
            OpenApiExample(
                "Valid request",
                value={"refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."},
            ),
            OpenApiExample(
                "Success response",
                response_only=True,
                value={"message": "Token refreshed"},
            ),
        ],
        tags=["Authentication"],
    )
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            set_jwt_cookies(
                response,
                response.data.get("access"),
                response.data.get("refresh"),
            )
            response.data = {"message": "Token refreshed"}
        return response
