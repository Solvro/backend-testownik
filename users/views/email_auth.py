from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from users.auth_cookies import set_jwt_cookies
from users.models import EmailLoginToken, User
from users.serializers import UserTokenObtainPairSerializer
from users.services import migrate_guest_to_user
from users.utils import send_login_email_to_user


def _banned_user_response(user):
    return Response(
        {
            "error": "user_banned",
            "detail": "Your account has been banned.",
            "ban_reason": user.ban_reason or "No reason provided",
        },
        status=403,
    )


def _login_success_response(user):
    refresh = UserTokenObtainPairSerializer.get_token(user)
    response = Response({"message": "Login successful"})
    set_jwt_cookies(response, str(refresh.access_token), str(refresh))
    return response


def _finalize_token_login(email_login_token, guest_id=""):
    user = email_login_token.user
    email_login_token.delete()

    if user.is_banned:
        return _banned_user_response(user)

    if guest_id:
        migrate_guest_to_user(guest_id, user)

    return _login_success_response(user)


class GenerateOtpView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(ratelimit(key="ip", rate="3/m", method="POST", block=True))
    @extend_schema(
        summary="Request login OTP",
        description="Send a one-time password (OTP) to a user's email to initiate login.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "format": "email"},
                },
                "required": ["email"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
            },
            403: OpenApiResponse(description="Rate limit exceeded."),
            404: OpenApiResponse(description="Not found."),
        },
        examples=[
            OpenApiExample(
                "Valid request",
                value={"email": "user@example.com"},
            ),
            OpenApiExample(
                "Success response",
                response_only=True,
                value={"message": "Login email sent."},
            ),
        ],
        tags=["Authentication"],
    )
    def post(self, request):
        email = request.data.get("email")
        user = User.objects.filter(email=email).first()
        if not user:
            # To prevent user enumeration, we return the same message
            return Response({"message": "Login email sent."})

        send_login_email_to_user(user)
        return Response({"message": "Login email sent."})


class LoginOtpView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(ratelimit(key="ip", rate="10/m", method="POST", block=True))
    @extend_schema(
        summary="Verify OTP for login",
        description="Verify the OTP provided by the user and return JWT tokens.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "format": "email"},
                    "otp": {"type": "string"},
                    "guest_id": {"type": "string"},
                },
                "required": ["email", "otp"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
            },
            400: OpenApiResponse(
                description=(
                    "`Email and OTP code must be provided` | "
                    "`Invalid OTP code` | "
                    "`OTP code expired or retries limit reached`"
                )
            ),
            403: OpenApiResponse(
                description="You do not have permission to perform this action. (Rate limit exceeded)"
            ),
            404: OpenApiResponse(description="Not found."),
        },
        examples=[
            OpenApiExample("Valid request", value={"email": "user@example.com", "otp": "123456"}),
            OpenApiExample(
                "Success response",
                response_only=True,
                value={"message": "Login successful"},
            ),
            OpenApiExample(
                "Error response (missing fields)",
                response_only=True,
                value={"error": "Email and OTP code must be provided"},
                status_codes=["400"],
            ),
            OpenApiExample(
                "Error response (invalid OTP)",
                response_only=True,
                value={"error": "Invalid OTP code"},
                status_codes=["400"],
            ),
            OpenApiExample(
                "Error response (expired OTP)",
                response_only=True,
                value={"error": "OTP code expired or retries limit reached"},
                status_codes=["400"],
            ),
            OpenApiExample(
                "Error response (rate limit exceeded)",
                response_only=True,
                value={"detail": "You do not have permission to perform this action."},
                status_codes=["403"],
            ),
        ],
        tags=["Authentication"],
    )
    def post(self, request):
        email = request.data.get("email")
        otp_code = request.data.get("otp")
        guest_id = request.data.get("guest_id", "")

        if not email or not otp_code:
            return Response({"error": "Email and OTP code must be provided"}, status=400)

        email_login_token = EmailLoginToken.objects.filter(user__email=email, otp_code=otp_code).first()

        if not email_login_token:
            for token in EmailLoginToken.objects.filter(user__email=email):
                token.add_retry()
            return Response({"error": "Invalid OTP code"}, status=400)

        if email_login_token.is_expired() or email_login_token.is_locked:
            email_login_token.delete()
            return Response({"error": "OTP code expired or retries limit reached"}, status=400)

        return _finalize_token_login(email_login_token, guest_id)


class LoginLinkView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="Verify login link token",
        description="Verify a token from a login email link and return JWT tokens upon success.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                    "guest_id": {"type": "string"},
                },
                "required": ["token"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
            },
            400: OpenApiResponse(description=("`Token not provided` | `Invalid or expired login link`")),
            404: OpenApiResponse(description="Not found."),
        },
        examples=[
            OpenApiExample("Valid token request", value={"token": "sometokenvalue123"}),
            OpenApiExample(
                "Success response",
                response_only=True,
                value={"message": "Login successful"},
            ),
            OpenApiExample(
                "Error response (missing token)",
                response_only=True,
                value={"error": "Token not provided"},
                status_codes=["400"],
            ),
            OpenApiExample(
                "Error response (invalid token)",
                response_only=True,
                value={"error": "Invalid or expired login link"},
                status_codes=["400"],
            ),
        ],
        tags=["Authentication"],
    )
    def post(self, request):
        token = request.data.get("token")
        guest_id = request.data.get("guest_id", "")
        if not token:
            return Response({"error": "Token not provided"}, status=400)

        email_login_token = EmailLoginToken.objects.filter(token=token).first()

        if not email_login_token or email_login_token.is_expired() or email_login_token.is_locked:
            if email_login_token:
                email_login_token.delete()
            return Response({"error": "Invalid or expired login link"}, status=400)

        return _finalize_token_login(email_login_token, guest_id)