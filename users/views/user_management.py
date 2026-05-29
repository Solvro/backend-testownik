import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from quizzes.models import Quiz, QuizSession, SharedQuiz
from quizzes.permissions import IsInternalApiRequest
from uploads.models import UploadedImage
from uploads.utils import process_uploaded_image
from users.auth_cookies import set_jwt_cookies
from users.models import StudyGroup, User, UserSettings
from users.serializers import (
    PublicUserSerializer,
    StudyGroupSerializer,
    UserSerializer,
    UserSettingsSerializer,
    UserTokenObtainPairSerializer,
)

logger = logging.getLogger(__name__)


class SettingsViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = UserSettingsSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        """
        Get or create settings for the current user.
        """
        user_settings, _ = UserSettings.objects.get_or_create(user=self.request.user)
        return user_settings

    @extend_schema(
        summary="Get user settings",
        description="Retrieve the current authenticated user's settings.",
        responses={
            200: UserSettingsSerializer,
        },
        examples=[
            OpenApiExample(
                "Sample Settings",
                value={
                    "sync_progress": True,
                    "initial_reoccurrences": 1,
                    "wrong_answer_reoccurrences": 1,
                    "notify_quiz_shared": False,
                    "notify_bug_reported": False,
                    "notify_marketing": True,
                },
            )
        ],
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Update user settings (full update)",
        description="Update all fields of the current authenticated user's settings.",
        request=UserSettingsSerializer,
        responses={
            200: UserSettingsSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
        examples=[
            OpenApiExample(
                "Successful Update",
                value={
                    "sync_progress": True,
                    "initial_reoccurrences": 2,
                    "wrong_answer_reoccurrences": 1,
                    "notify_quiz_shared": False,
                    "notify_bug_reported": True,
                    "notify_marketing": True,
                },
            )
        ],
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(
        summary="Update user settings (partial update)",
        description="Update specific fields of the current authenticated user's settings.",
        request=UserSettingsSerializer,
        responses={
            200: UserSettingsSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
        examples=[
            OpenApiExample(
                "Partial Update",
                value={
                    "sync_progress": False,
                },
            )
        ],
    )
    def partial_update(self, request, *args, **kwargs):
        """PATCH /api/settings/"""
        return super().partial_update(request, *args, **kwargs)


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
        allowed_fields_patch = {"hide_profile"}
        data = request.data

        disallowed = set(data) - allowed_fields_patch
        if disallowed:
            return Response(
                f"Field '{next(iter(disallowed))}' is not allowed to be updated",
                status=400,
            )

        serializer = self.get_serializer(request.user, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)


class UserPhotoView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Upload custom profile photo",
        description="Uploads a custom profile photo, compresses it to AVIF, and sets it for the user.",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "photo": {
                        "type": "string",
                        "format": "binary",
                    }
                },
                "required": ["photo"],
            }
        },
        responses={200: OpenApiResponse(description="Photo uploaded successfully")},
    )
    def post(self, request):
        if "photo" not in request.FILES:
            return Response({"error": "No photo provided"}, status=400)

        try:
            processed_file, width, height, content_type = process_uploaded_image(request.FILES["photo"])
        except ValidationError:
            logger.exception("Photo upload failed for user %s", request.user.id)
            return Response(
                {"error": "Invalid image file. Accepted formats: JPEG, PNG, GIF, WEBP, AVIF (max 10MB)."}, status=400
            )

        img = UploadedImage.objects.create(
            image=processed_file,
            original_filename=request.FILES["photo"].name,
            content_type=content_type,
            file_size=processed_file.size,
            width=width,
            height=height,
            uploaded_by=request.user,
        )

        request.user.custom_photo_image = img
        request.user.save(update_fields=["custom_photo_image"])

        return Response({"message": "Photo uploaded successfully"})

    @extend_schema(
        summary="Delete custom profile photo",
        description="Removes the custom profile photo, reverting to the USOS/DiceBear photo.",
        responses={200: OpenApiResponse(description="Photo removed successfully")},
    )
    def delete(self, request):
        request.user.custom_photo_image = None
        request.user.save(update_fields=["custom_photo_image"])
        return Response({"message": "Photo removed successfully"})


class UserViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = User.objects.select_related("photo_image", "custom_photo_image").all()
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


class GuestCreateView(APIView):
    """Create a guest account with no credentials. Returns JWT tokens for immediate use."""

    permission_classes = [IsInternalApiRequest]

    @extend_schema(
        summary="Create guest account",
        description="Creates a new guest account automatically without requiring any data. "
        "Returns JWT tokens in cookies for immediate use.",
        request=None,
        responses={
            201: {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
            },
            403: OpenApiResponse(description="Forbidden - internal API access only"),
        },
    )
    def post(self, request):
        user = User.objects.create_guest_user()
        refresh = UserTokenObtainPairSerializer.get_token(user)

        response = Response({"message": "Guest account created"}, status=201)
        set_jwt_cookies(response, str(refresh.access_token), str(refresh))
        return response


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
        transfer_to_user_id = request.data.get("transfer_to_user_id")
        transfer_to_user = None

        if transfer_to_user_id:
            try:
                transfer_to_user = User.objects.get(id=transfer_to_user_id)
            except User.DoesNotExist:
                return Response({"error": "User to transfer quizzes to not found"}, status=404)
            if transfer_to_user.root_folder is None:
                return Response(
                    {"error": "Transfer target user has no root folder"},
                    status=400,
                )

        with transaction.atomic():
            if transfer_to_user is not None:
                Quiz.objects.filter(creator=request.user).update(
                    creator=transfer_to_user,
                    folder=transfer_to_user.root_folder,
                )

            QuizSession.objects.filter(user=request.user).delete()
            SharedQuiz.objects.filter(user=request.user).delete()
            request.user.delete()

        return Response({"message": "Account deleted successfully"})
