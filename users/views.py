import json
import logging
import os
from asyncio import CancelledError, sleep
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import dotenv
from asgiref.sync import sync_to_async
from django.contrib import messages
from django.contrib.auth import aget_user
from django.contrib.auth import alogin as async_auth_login
from django.contrib.auth import login as auth_login
from django.db.models import Q
from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
)
from django.shortcuts import redirect, render
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import mixins, permissions, viewsets
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from usos_api import USOSAPIException, USOSClient

from quizzes.models import QuizProgress, SharedQuiz
from testownik_core.settings import oauth
from users.models import EmailLoginToken, StudyGroup, Term, User, UserSettings
from users.serializers import PublicUserSerializer, StudyGroupSerializer, UserSerializer
from users.utils import send_login_email_to_user

dotenv.load_dotenv()

logger = logging.getLogger(__name__)


def add_query_params(url, params):
    url_parts = list(urlparse(url))
    query = dict(parse_qs(url_parts[4]))
    query.update(params)
    url_parts[4] = urlencode(query, doseq=True)
    return str(urlunparse(url_parts))


def remove_query_params(url, params):
    url_parts = list(urlparse(url))
    query = dict(parse_qs(url_parts[4]))
    for param in params:
        query.pop(param, None)
    url_parts[4] = urlencode(query, doseq=True)
    return str(urlunparse(url_parts))


def login(request):
    confirm_user = request.GET.get("confirm_user", "false") == "true"
    jwt = request.GET.get("jwt", "false") == "true"
    redirect_url = request.GET.get("redirect", "")
    callback_url = request.build_absolute_uri(
        f"/authorize/?jwt={str(jwt).lower()}{f'&redirect={redirect_url}' if redirect_url else ''}"
    )
    additional_params = {}
    if confirm_user:
        additional_params["prompt"] = "login"
    return oauth.create_client("solvro-auth").authorize_redirect(request, callback_url, **additional_params)


async def login_usos(request):
    confirm_user = request.GET.get("confirm_user", "false") == "true"
    jwt = request.GET.get("jwt", "false") == "true"
    redirect_url = request.GET.get("redirect", "")

    if jwt and not redirect_url:
        return HttpResponseForbidden("Redirect URL must be provided when using JWT")

    callback_url = request.build_absolute_uri(
        f"/authorize/usos/?jwt={str(jwt).lower()}{f'&redirect={redirect_url}' if redirect_url else ''}"
    )

    max_retries = 3  # max tries
    retry_delay = 2  # time before next try (seconds)

    for attempt in range(max_retries):
        try:
            async with USOSClient(
                "https://apps.usos.pwr.edu.pl/",
                os.getenv("USOS_CONSUMER_KEY"),
                os.getenv("USOS_CONSUMER_SECRET"),
                trust_env=True,
            ) as client:
                client.set_scopes(["offline_access", "studies", "email", "photo", "grades"])
                authorization_url = await client.get_authorization_url(callback_url, confirm_user)
                request_token, request_token_secret = client.connection.auth_manager.get_request_token()
                await request.session.aset(f"request_token_{request_token}", request_token_secret)
                request.session.modified = True

            return redirect(authorization_url)

        except Exception as e:
            if isinstance(e, CancelledError):
                raise

            if attempt < max_retries - 1:
                await sleep(retry_delay)
                continue
            return redirect(add_query_params(redirect_url, {"error": "usos_unavailable"}))
    return redirect(add_query_params(redirect_url, {"error": "usos_unavailable"}))


def admin_login(request):
    next_url = request.GET.get("next", "/admin")
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect(next_url)
    return render(request, "users/admin_login.html", {"next": next_url, "username": request.user})


def authorize(request):
    token = oauth.create_client("solvro-auth").authorize_access_token(request)
    resp = oauth.create_client("solvro-auth").get(
        "https://auth.solvro.pl/realms/solvro/protocol/openid-connect/userinfo",
        token=token,
    )
    resp.raise_for_status()
    profile = resp.json()

    redirect_url = request.GET.get("redirect", "index")

    if not profile.get("email"):
        if request.GET.get("jwt", "false") == "true":
            return redirect(add_query_params(redirect_url, {"error": "no_email"}))
        messages.error(request, "Brak adresu email w profilu użytkownika.")
        return redirect(redirect_url)

    user, created = User.objects.update_or_create(
        email=profile["email"],
        defaults={
            "photo_url": f"https://api.dicebear.com/9.x/adventurer/svg?seed={profile['email']}",
        },
    )

    if request.GET.get("jwt", "false") == "true":
        refresh = RefreshToken.for_user(user)
        return redirect(
            add_query_params(
                remove_query_params(redirect_url, ["error"]),
                {
                    "access_token": str(refresh.access_token),
                    "refresh_token": str(refresh),
                },
            )
        )

    auth_login(request, user)
    return redirect(redirect_url)


async def authorize_usos(request):
    redirect_url = request.GET.get("redirect", "index")

    async with USOSClient(
        "https://apps.usos.pwr.edu.pl/",
        os.getenv("USOS_CONSUMER_KEY"),
        os.getenv("USOS_CONSUMER_SECRET"),
        trust_env=True,
    ) as client:
        verifier = request.GET.get("oauth_verifier")
        request_token = request.GET.get("oauth_token")
        request_token_secret = await request.session.apop(f"request_token_{request_token}", None)
        if not request_token_secret:
            if request.GET.get("retry") != "1":
                login_url = request.build_absolute_uri("/api/login/usos/")
                params = request.GET.copy()
                params["retry"] = "1"
                return redirect(add_query_params(login_url, dict(params)))

            if request.GET.get("jwt", "false") == "true":
                return redirect(add_query_params(redirect_url, {"error": "invalid_token"}))
            return HttpResponseForbidden()

        try:
            access_token, access_token_secret = await client.authorize(verifier, request_token, request_token_secret)
        except USOSAPIException as e:
            logger.exception(f"Error during USOS authorization: {e}")
            if request.GET.get("retry") != "1":
                login_url = request.build_absolute_uri("/api/login/usos/")
                params = request.GET.copy()
                params["retry"] = "1"
                return redirect(add_query_params(login_url, dict(params)))

            if request.GET.get("jwt", "false") == "true":
                return redirect(add_query_params(redirect_url, {"error": "authorization_failed"}))
            return HttpResponseForbidden()

        user, created = await update_user_data_from_usos(client, access_token, access_token_secret)

        if not user.is_student_and_not_staff:
            messages.error(
                request,
                "Aby korzystać z Testownika, musisz być aktywnym studentem Politechniki Wrocławskiej.",
            )
            if created:
                await user.adelete()
            if request.GET.get("jwt", "false") == "true":
                return redirect(add_query_params(redirect_url, {"error": "not_student"}))
            return redirect("index")

    if request.GET.get("jwt", "false") == "true":
        refresh = await sync_to_async(RefreshToken.for_user)(user)
        return redirect(
            add_query_params(
                remove_query_params(redirect_url, ["error"]),
                {
                    "access_token": str(refresh.access_token),
                    "refresh_token": str(refresh),
                },
            )
        )

    await async_auth_login(request, user)
    return redirect(redirect_url)


async def update_user_data_from_usos(client=None, access_token=None, access_token_secret=None):
    if not client:
        if not access_token or not access_token_secret:
            raise ValueError("Either client or access_token and access_token_secret must be provided")
        async with USOSClient(
            "https://apps.usos.pwr.edu.pl/",
            os.getenv("USOS_CONSUMER_KEY"),
            os.getenv("USOS_CONSUMER_SECRET"),
            trust_env=True,
        ) as client:
            client.load_access_token(access_token, access_token_secret)
            user_data = await client.user_service.get_user()
    else:
        user_data = await client.user_service.get_user()

    defaults = {
        "first_name": user_data.first_name,
        "last_name": user_data.last_name,
        "email": user_data.email,
        "student_number": user_data.student_number,
        "sex": user_data.sex.value,
        "student_status": user_data.student_status.value,
        "staff_status": user_data.staff_status.value,
        "photo_url": user_data.photo_urls.get(
            "original",
            user_data.photo_urls.get("200x200", next(iter(user_data.photo_urls.values()), None)),
        ),
    }

    if access_token and access_token_secret:
        defaults["access_token"] = access_token
        defaults["access_token_secret"] = access_token_secret

    user_obj, created = await User.objects.aupdate_or_create(usos_id=user_data.id, defaults=defaults)

    if created:
        user_obj.set_unusable_password()
        await user_obj.asave()

    user_groups = await client.group_service.get_groups_for_participant(
        fields=[
            "course_unit_id",
            "group_number",
            "course_name",
            "term_id",
            "class_type",
        ]
    )

    for group in user_groups:
        try:
            term = await Term.objects.aget(
                id=group.term_id,
            )
        except Term.DoesNotExist:
            term_response = await client.term_service.get_term(group.term_id)
            term = await Term.objects.acreate(
                id=term_response.id,
                name=term_response.name.pl,
                start_date=term_response.start_date,
                end_date=term_response.end_date,
                finish_date=term_response.finish_date,
            )
        group_obj, _ = await StudyGroup.objects.aupdate_or_create(
            id=f"{group.course_unit_id}-{group.group_number}",
            defaults={
                "name": f"{group.course_name.pl} - {group.class_type.pl}, grupa {group.group_number}",
                "term": term,
            },
        )
        await user_obj.study_groups.aadd(group_obj)

    return user_obj, created


class SettingsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get user settings",
        description="Retrieve the current authenticated user's settings.",
        responses={
            200: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "Sample Settings",
                value={
                    "sync_progress": True,
                    "initial_reoccurrences": 3,
                    "wrong_answer_reoccurrences": 1,
                },
            )
        ],
    )
    def get(self, request):
        try:
            user_settings = request.user.settings
        except UserSettings.DoesNotExist:
            user_settings = UserSettings(user=request.user)
            user_settings.save()

        return Response(
            {
                "sync_progress": user_settings.sync_progress,
                "initial_reoccurrences": user_settings.initial_reoccurrences,
                "wrong_answer_reoccurrences": user_settings.wrong_answer_reoccurrences,
            }
        )

    @extend_schema(
        summary="Update user settings",
        description="Update the current authenticated user's settings.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "sync_progress": {"type": "boolean"},
                    "initial_reoccurrences": {"type": "integer", "minimum": 1},
                    "wrong_answer_reoccurrences": {"type": "integer", "minimum": 0},
                },
                "required": [],
            }
        },
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiResponse(description="Validation error"),
        },
        examples=[
            OpenApiExample(
                "Successful Update",
                value={
                    "sync_progress": True,
                    "initial_reoccurrences": 3,
                    "wrong_answer_reoccurrences": 2,
                },
            )
        ],
    )
    def put(self, request):
        data = request.data

        try:
            user_settings = request.user.settings
        except UserSettings.DoesNotExist:
            user_settings = UserSettings(user=request.user)

        sync_progress = data.get("sync_progress")
        initial_reoccurrences = data.get("initial_reoccurrences")
        wrong_answer_reoccurrences = data.get("wrong_answer_reoccurrences")

        if sync_progress is not None:
            user_settings.sync_progress = sync_progress

        if initial_reoccurrences is not None:
            if initial_reoccurrences >= 1:
                user_settings.initial_reoccurrences = initial_reoccurrences
            else:
                return Response(
                    "Initial repetitions must be ≥ 1",
                    status=HttpResponseBadRequest.status_code,
                )

        if wrong_answer_reoccurrences is not None:
            if wrong_answer_reoccurrences >= 0:
                user_settings.wrong_answer_reoccurrences = wrong_answer_reoccurrences
            else:
                return Response(
                    "Wrong answer repetitions must be ≥ 0",
                    status=HttpResponseBadRequest.status_code,
                )

        user_settings.save()
        return Response(
            {
                "sync_progress": user_settings.sync_progress,
                "initial_reoccurrences": user_settings.initial_reoccurrences,
                "wrong_answer_reoccurrences": user_settings.wrong_answer_reoccurrences,
            }
        )


async def refresh_user_data(request):
    try:
        request_user = await aget_user(request)
        await update_user_data_from_usos(
            access_token=request_user.access_token,
            access_token_secret=request_user.access_token_secret,
        )
    except Exception as e:
        messages.error(request, f"Wystąpił błąd podczas odświeżania danych użytkownika: {e}")
    return redirect(request.GET.get("next", "index"))


class CurrentUserView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    @extend_schema(
        summary="Get current user profile",
        description="Returns basic information about the currently authenticated user.",
    )
    def get(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    @extend_schema(
        summary="Update current user profile",
        description="Update limited fields in the user's profile.",
    )
    def patch(self, request):
        allowed_fields_patch = ["overriden_photo_url", "hide_profile"]
        data = json.loads(request.body)

        for key in data:  # Check if all fields are allowed
            if key not in allowed_fields_patch:
                return Response(
                    f"Field '{key}' is not allowed to be updated",
                    status=HttpResponseBadRequest.status_code,
                )

        serializer = self.get_serializer(request.user, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=HttpResponseBadRequest.status_code)


class UserViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = User.objects.all()
    serializer_class = PublicUserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        search = self.request.query_params.get("search", "").strip()
        if search and len(search) >= 3:
            search_terms = search.split(" ")
            filters = Q()
            if len(search_terms) == 1:
                filters |= Q(first_name__icontains=search_terms[0], hide_profile=False)
                filters |= Q(last_name__icontains=search_terms[0], hide_profile=False)
                filters |= Q(student_number=search_terms[0])
            elif len(search_terms) == 2:
                filters |= Q(
                    first_name__icontains=search_terms[0],
                    last_name__icontains=search_terms[1],
                    hide_profile=False,
                )
                filters |= Q(
                    first_name__icontains=search_terms[1],
                    last_name__icontains=search_terms[0],
                    hide_profile=False,
                )
                filters |= Q(
                    first_name__icontains=search_terms[0],
                    student_number__icontains=search_terms[1],
                    hide_profile=False,
                )
                filters |= Q(
                    first_name__icontains=search_terms[1],
                    student_number__icontains=search_terms[0],
                    hide_profile=False,
                )
            elif len(search_terms) == 3:
                filters |= Q(
                    first_name__icontains=search_terms[0],
                    last_name__icontains=search_terms[1],
                    student_number__icontains=search_terms[2],
                )
                filters |= Q(
                    first_name__icontains=search_terms[0],
                    last_name__icontains=search_terms[2],
                    student_number__icontains=search_terms[1],
                )
                filters |= Q(
                    first_name__icontains=search_terms[1],
                    last_name__icontains=search_terms[0],
                    student_number__icontains=search_terms[2],
                )
                filters |= Q(
                    first_name__icontains=search_terms[1],
                    last_name__icontains=search_terms[2],
                    student_number__icontains=search_terms[0],
                )
                filters |= Q(
                    first_name__icontains=search_terms[2],
                    last_name__icontains=search_terms[0],
                    student_number__icontains=search_terms[1],
                )
                filters |= Q(
                    first_name__icontains=search_terms[2],
                    last_name__icontains=search_terms[1],
                    student_number__icontains=search_terms[0],
                )
            else:
                return User.objects.none()
            return User.objects.filter(filters)
        else:
            return User.objects.none()


class StudyGroupViewSet(viewsets.ModelViewSet):
    queryset = StudyGroup.objects.all()
    serializer_class = StudyGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = StudyGroup.objects.filter(members=self.request.user)

        return queryset


class GenerateOtpView(APIView):
    permission_classes = [AllowAny]

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
            404: OpenApiResponse(description="User not found"),
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
            OpenApiExample(
                "Error response (user not found)",
                response_only=True,
                value={"error": "User not found"},
                status_codes=["404"],
            ),
        ],
    )
    def post(self, request):
        email = request.data.get("email")
        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "User not found"}, status=404)

        send_login_email_to_user(user)
        return Response({"message": "Login email sent."})


class LoginOtpView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Verify OTP for login",
        description="Verify the OTP provided by the user and return JWT tokens.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "format": "email"},
                    "otp": {"type": "string"},
                },
                "required": ["email", "otp"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "access_token": {"type": "string"},
                    "refresh_token": {"type": "string"},
                },
            },
            400: OpenApiResponse(description="Invalid or expired OTP"),
        },
        examples=[
            OpenApiExample("Valid request", value={"email": "user@example.com", "otp": "123456"}),
            OpenApiExample(
                "Success response",
                response_only=True,
                value={
                    "access_token": "eyJ0eXAiOiJKV1QiLCJh...",
                    "refresh_token": "eyJ0eXAiOiJKV1QiLCJi...",
                },
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
        ],
    )
    def post(self, request):
        email = request.data.get("email")
        otp_code = request.data.get("otp")

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

        user = email_login_token.user
        refresh = RefreshToken.for_user(user)
        email_login_token.delete()

        return Response(
            {
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh),
            }
        )


class LoginLinkView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Verify login link token",
        description="Verify a token from a login email link and return JWT tokens upon success.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                },
                "required": ["token"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "access_token": {"type": "string"},
                    "refresh_token": {"type": "string"},
                },
            },
            400: OpenApiResponse(description="Token not provided or invalid/expired"),
        },
        examples=[
            OpenApiExample("Valid token request", value={"token": "sometokenvalue123"}),
            OpenApiExample(
                "Success response",
                response_only=True,
                value={
                    "access_token": "eyJ0eXAiOiJKV1QiLCJh...",
                    "refresh_token": "eyJ0eXAiOiJKV1QiLCJi...",
                },
            ),
            OpenApiExample(
                "Error response (invalid token)",
                response_only=True,
                value={"error": "Invalid or expired login link"},
                status_codes=["400"],
            ),
        ],
    )
    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response({"error": "Token not provided"}, status=400)

        email_login_token = EmailLoginToken.objects.filter(token=token).first()

        if not email_login_token or email_login_token.is_expired() or email_login_token.is_locked:
            if email_login_token:
                email_login_token.delete()
            return Response({"error": "Invalid or expired login link"}, status=400)

        user = email_login_token.user
        refresh = RefreshToken.for_user(user)
        email_login_token.delete()

        return Response(
            {
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh),
            }
        )


class DeleteAccountView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Delete user account",
        description="Deletes the user account. Optionally transfer quizzes to another user.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "transfer_to_user_id": {"type": "string", "format": "uuid"},
                },
                "required": [],
            }
        },
        responses={
            200: OpenApiTypes.OBJECT,
            404: OpenApiResponse(description="Transfer target user not found"),
        },
        examples=[
            OpenApiExample("Delete without transferring quizzes", value={}),
            OpenApiExample(
                "Delete and transfer quizzes to another user",
                value={"transfer_to_user_id": "123e4567-e89b-12d3-a456-426614174000"},
            ),
            OpenApiExample(
                "Success response",
                response_only=True,
                value={"message": "Account deleted successfully"},
            ),
        ],
    )
    def post(self, request):
        from quizzes.models import Quiz

        data = json.loads(request.body)
        transfer_to_user_id = data.get("transfer_to_user_id")

        if transfer_to_user_id:
            try:
                transfer_to_user = User.objects.get(id=transfer_to_user_id)
            except User.DoesNotExist:
                return Response({"error": "User to transfer quizzes to not found"}, status=404)

            quizzes = Quiz.objects.filter(maintainer=request.user)
            for quiz in quizzes:
                quiz.maintainer = transfer_to_user
                quiz.save()

        QuizProgress.objects.filter(user=request.user).delete()
        SharedQuiz.objects.filter(user=request.user).delete()
        request.user.delete()

        return Response({"message": "Account deleted successfully"})
