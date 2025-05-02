import json
import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import dotenv
from asgiref.sync import sync_to_async
from django.contrib import messages
from django.contrib.auth import aget_user
from django.contrib.auth import alogin as auth_login
from django.db.models import Q
from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
)
from django.shortcuts import redirect, render
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from usos_api import USOSClient
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample

from users.models import EmailLoginToken, StudyGroup, Term, User, UserSettings
from users.serializers import PublicUserSerializer, StudyGroupSerializer, UserSerializer
from users.utils import send_login_email_to_user

dotenv.load_dotenv()


def add_query_params(url, params):
    url_parts = list(urlparse(url))
    query = dict(parse_qs(url_parts[4]))
    query.update(params)
    url_parts[4] = urlencode(query, doseq=True)
    return urlunparse(url_parts)


def remove_query_params(url, params):
    url_parts = list(urlparse(url))
    query = dict(parse_qs(url_parts[4]))
    for param in params:
        query.pop(param, None)
    url_parts[4] = urlencode(query, doseq=True)
    return urlunparse(url_parts)


async def login_usos(request):
    confirm_user = request.GET.get("confirm_user", "false") == "true"
    jwt = request.GET.get("jwt", "false") == "true"
    redirect_url = request.GET.get("redirect", "")

    if jwt and not redirect_url:
        return HttpResponseForbidden("Redirect URL must be provided when using JWT")

    callback_url = request.build_absolute_uri(
        f"/authorize/?jwt={str(jwt).lower()}{f'&redirect={redirect_url}' if redirect_url else ''}"
    )

    async with USOSClient(
        "https://apps.usos.pwr.edu.pl/",
        os.getenv("USOS_CONSUMER_KEY"),
        os.getenv("USOS_CONSUMER_SECRET"),
        trust_env=True,
    ) as client:
        client.set_scopes(["offline_access", "studies", "email", "photo", "grades"])
        authorization_url = await client.get_authorization_url(
            callback_url, confirm_user
        )
        request_token, request_token_secret = (
            client.connection.auth_manager.get_request_token()
        )
        await request.session.aset(
            f"request_token_{request_token}", request_token_secret
        )
        request.session.modified = True

    return redirect(authorization_url)


def admin_login(request):
    next_url = request.GET.get("next", "/admin")
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect(next_url)
    return render(
        request, "users/admin_login.html", {"next": next_url, "username": request.user}
    )


async def authorize(request):
    redirect_url = request.GET.get("redirect", "index")

    async with USOSClient(
        "https://apps.usos.pwr.edu.pl/",
        os.getenv("USOS_CONSUMER_KEY"),
        os.getenv("USOS_CONSUMER_SECRET"),
        trust_env=True,
    ) as client:
        verifier = request.GET.get("oauth_verifier")
        request_token = request.GET.get("oauth_token")
        request_token_secret = await request.session.apop(
            f"request_token_{request_token}", None
        )
        if not request_token_secret:
            return HttpResponseForbidden()

        access_token, access_token_secret = await client.authorize(
            verifier, request_token, request_token_secret
        )
        user, created = await update_user_data_from_usos(
            client, access_token, access_token_secret
        )

        if not user.is_student_and_not_staff:
            messages.error(
                request,
                "Aby korzystać z Testownika, musisz być aktywnym studentem Politechniki Wrocławskiej.",
            )
            if created:
                await user.adelete()
            if request.GET.get("jwt", "false") == "true":
                return redirect(
                    add_query_params(redirect_url, {"error": "not_student"})
                )
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

    await auth_login(request, user)
    return redirect(redirect_url)


async def update_user_data_from_usos(
    client=None, access_token=None, access_token_secret=None
):
    if not client:
        if not access_token or not access_token_secret:
            raise ValueError(
                "Either client or access_token and access_token_secret must be provided"
            )
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
            user_data.photo_urls.get(
                "200x200", next(iter(user_data.photo_urls.values()), None)
            ),
        ),
    }

    if access_token and access_token_secret:
        defaults["access_token"] = access_token
        defaults["access_token_secret"] = access_token_secret

    user_obj, created = await User.objects.aupdate_or_create(
        usos_id=user_data.id, defaults=defaults
    )

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


@api_view(["GET", "PUT"])
def settings(request):
    if request.method == "GET":
        return get_user_settings(request)
    elif request.method == "PUT":
        return update_user_settings(request)
    else:
        return Response(status=HttpResponseNotAllowed.status_code)


def get_user_settings(request):
    if not request.user.is_authenticated:
        return Response(status=HttpResponseForbidden.status_code)

    try:
        user_settings = request.user.settings
    except UserSettings.DoesNotExist:
        user_settings = UserSettings(user=request.user)

    settings_data = {
        "sync_progress": user_settings.sync_progress,
        "initial_reoccurrences": user_settings.initial_reoccurrences,
        "wrong_answer_reoccurrences": user_settings.wrong_answer_reoccurrences,
    }

    return Response(settings_data)


def update_user_settings(request):
    if not request.user.is_authenticated:
        return Response(status=HttpResponseForbidden.status_code)

    data = json.loads(request.body)

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
                "Initial repetitions must be greater or equal to 1",
                status=HttpResponseBadRequest.status_code,
            )

    if wrong_answer_reoccurrences is not None:
        if wrong_answer_reoccurrences >= 0:
            user_settings.wrong_answer_reoccurrences = wrong_answer_reoccurrences
        else:
            return Response(
                "Wrong answer repetitions must be greater or equal to 0",
                status=HttpResponseBadRequest.status_code,
            )

    user_settings.save()
    return Response(status=200)


async def refresh_user_data(request):
    try:
        request_user = await aget_user(request)
        await update_user_data_from_usos(
            access_token=request_user.access_token,
            access_token_secret=request_user.access_token_secret,
        )
    except Exception as e:
        messages.error(
            request, f"Wystąpił błąd podczas odświeżania danych użytkownika: {e}"
        )
    return redirect(request.GET.get("next", "index"))


@api_view(["GET", "PATCH"])
def current_user(request):
    allowed_fields_patch = [
        "overriden_photo_url",
        "hide_profile",
    ]
    if request.method == "PATCH":
        data = json.loads(request.body)
        for key in data.keys():  # Check if all fields are allowed
            if key not in allowed_fields_patch:
                return Response(
                    f"Field '{key}' is not allowed to be updated",
                    status=HttpResponseBadRequest.status_code,
                )
        serializer = UserSerializer(request.user, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        print(serializer.errors)
        return Response(serializer.errors, status=HttpResponseBadRequest.status_code)
    serializer = UserSerializer(request.user)
    return Response(serializer.data)


class UserViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
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


@api_view(["POST"])
@permission_classes([AllowAny])
def generate_otp(request):
    email = request.data.get("email")
    user = User.objects.filter(email=email).first()
    if not user:
        return Response({"error": "User not found"}, status=404)

    send_login_email_to_user(user)
    return Response({"message": "Login email sent."})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_otp(request):
    email = request.data.get("email")
    otp_code = request.data.get("otp")

    if not email or not otp_code:
        return Response({"error": "Email and OTP code must be provided"}, status=400)

    email_login_token = EmailLoginToken.objects.filter(
        user__email=email, otp_code=otp_code
    ).first()

    if not email_login_token:
        tokens_for_user = EmailLoginToken.objects.filter(user__email=email)
        for token in tokens_for_user:
            token.add_retry()
        return Response({"error": "Invalid OTP code"}, status=400)

    if email_login_token.is_expired():
        email_login_token.delete()
        return Response({"error": "OTP code expired"}, status=400)

    if email_login_token.is_locked:
        email_login_token.delete()
        return Response({"error": "OTP code retries limit reached"}, status=400)

    user = email_login_token.user
    refresh = RefreshToken.for_user(user)
    email_login_token.delete()
    return Response(
        {
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def login_link(request):
    token = request.data.get("token")
    if not token:
        return Response({"error": "Token not provided"}, status=400)

    email_login_token = EmailLoginToken.objects.filter(token=token).first()

    if not email_login_token:
        return Response({"error": "Invalid login link"}, status=400)

    if email_login_token.is_expired():
        email_login_token.delete()
        return Response({"error": "Login link expired"}, status=400)

    if email_login_token.is_locked:
        email_login_token.delete()
        return Response({"error": "Login link retries limit reached"}, status=400)

    user = email_login_token.user
    refresh = RefreshToken.for_user(user)
    email_login_token.delete()
    return Response(
        {
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
        }
    )


@extend_schema(
    summary="Delete user account",
    description="Delete the current user's account. Optionally transfer quiz ownership to another user before deletion.",
    parameters=[
        OpenApiParameter(
            name="transfer_to_user_id",
            description="ID of the user to transfer quizzes to before deletion",
            required=False,
            type=str,
            location=OpenApiParameter.QUERY,
        ),
    ],
    examples=[
        OpenApiExample(
            "Delete without transfer",
            value={},
            description="Delete account without transferring quizzes",
        ),
        OpenApiExample(
            "Delete with transfer",
            value={"transfer_to_user_id": "123e4567-e89b-12d3-a456-426614174000"},
            description="Delete account and transfer quizzes to another user",
        ),
    ],
    responses={
        200: {
            "description": "Account deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Account deleted successfully"}
                }
            }
        },
        401: {
            "description": "Unauthorized - User not authenticated",
            "content": {
                "application/json": {
                    "example": {"error": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "User to transfer quizzes to not found",
            "content": {
                "application/json": {
                    "example": {"error": "User to transfer quizzes to not found"}
                }
            }
        }
    }
)
@api_view(["POST"])
def delete_account(request):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)

    data = json.loads(request.body)
    transfer_to_user_id = data.get("transfer_to_user_id")
    
    # If transfer_to_user_id is provided, transfer quizzes to that user
    if transfer_to_user_id:
        try:
            transfer_to_user = User.objects.get(id=transfer_to_user_id)
        except User.DoesNotExist:
            return Response({"error": "User to transfer quizzes to not found"}, status=404)
        
        # Transfer all quizzes owned by the user
        quizzes = Quiz.objects.filter(maintainer=request.user)
        for quiz in quizzes:
            quiz.maintainer = transfer_to_user
            quiz.save()
    
    # Delete user settings
    try:
        request.user.settings.delete()
    except UserSettings.DoesNotExist:
        pass
    
    # Delete user's quiz progress
    QuizProgress.objects.filter(user=request.user).delete()
    
    # Delete user's shared quiz entries
    SharedQuiz.objects.filter(user=request.user).delete()
    
    # Delete the user
    request.user.delete()
    
    return Response({"message": "Account deleted successfully"})
