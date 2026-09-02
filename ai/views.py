from django.http.multipartparser import MultiPartParser
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from python_multipart import FormParser
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from quizzes.permissions import IsInternalApiRequest
from users.models import User

from .models import (
    AIAccountLimit,
    AIChatConversation,
    AIModel,
    AIUsageEvent,
    AIUsageSettings,
    AIUserLimitOverride,
)
from .permissions import CanManageAILimits, HasAIStatsPermission
from .selectors import get_admin_stats, get_admin_users
from .serializers import (
    AdminPermissionsSerializer,
    AdminStatsQuerySerializer,
    AdminStatsSerializer,
    AdminUserSerializer,
    AdminUsersQuerySerializer,
    AIAccountLimitSerializer,
    AIChatConversationListSerializer,
    AIChatConversationSerializer,
    AILimitsResetSerializer,
    AIModelSerializer,
    AIUsageEventSerializer,
    AIUsageSettingsSerializer,
    AIUsageSummarySerializer,
    AIUserLimitOverrideResponseSerializer,
    AIUserLimitOverrideSerializer,
    AvailableAIModelsSerializer,
    GenerateQuizFromPDFSerializer,
    InternalQuotaCheckSerializer,
    InternalUsageReportSerializer,
    MyUsageQuerySerializer,
    QuotaDecisionSerializer,
    UsageReportResultSerializer,
)
from .services import (
    AIUsageAccessDenied,
    available_models_for_user,
    check_quota,
    get_usage_summary,
    record_usage,
    reset_all_limits,
    soft_delete_model,
    generate_quiz_from_pdf,
)

INTERNAL_API_KEY_HEADER = OpenApiParameter(
    name="Api-Key",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Internal service API key.",
)


class AIUsagePagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 100


class InternalQuotaCheckView(generics.GenericAPIView):
    permission_classes = (IsInternalApiRequest,)
    serializer_class = InternalQuotaCheckSerializer

    @extend_schema(
        auth=[],
        parameters=[INTERNAL_API_KEY_HEADER],
        request=InternalQuotaCheckSerializer,
        responses={
            status.HTTP_200_OK: QuotaDecisionSerializer,
            status.HTTP_409_CONFLICT: QuotaDecisionSerializer,
            status.HTTP_429_TOO_MANY_REQUESTS: QuotaDecisionSerializer,
        },
    )
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = generics.get_object_or_404(User, pk=serializer.validated_data["user_id"])
        try:
            result = check_quota(
                user,
                estimated_input_tokens=serializer.validated_data.get("estimated_input_tokens"),
                scope=serializer.validated_data.get("scope"),
                requested_model=serializer.validated_data.get("requested_model"),
                available_providers=serializer.validated_data.get("available_providers"),
            )
        except AIUsageAccessDenied as error:
            return Response({"code": error.code}, status=status.HTTP_403_FORBIDDEN)
        response_status = (
            status.HTTP_409_CONFLICT
            if result["exceeded_window"] == "model_unavailable"
            else status.HTTP_200_OK
            if result["allowed"]
            else status.HTTP_429_TOO_MANY_REQUESTS
        )
        return Response(QuotaDecisionSerializer(result).data, status=response_status)


class InternalUsageReportView(generics.GenericAPIView):
    permission_classes = (IsInternalApiRequest,)
    serializer_class = InternalUsageReportSerializer

    @extend_schema(
        auth=[],
        parameters=[INTERNAL_API_KEY_HEADER],
        request=InternalUsageReportSerializer,
        responses={
            status.HTTP_200_OK: UsageReportResultSerializer,
            status.HTTP_201_CREATED: UsageReportResultSerializer,
        },
    )
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data.copy()
        user = generics.get_object_or_404(User, pk=data.pop("user_id"))
        try:
            event, created = record_usage(user=user, **data)
        except ValueError:
            return Response(
                {"detail": "Unable to process the usage report."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = UsageReportResultSerializer({"id": event.id, "credits": event.credits, "created": created})
        return Response(
            result.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class MyUsageView(generics.GenericAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = AIUsageSummarySerializer

    @extend_schema(parameters=[MyUsageQuerySerializer], responses=AIUsageSummarySerializer)
    def get(self, request):
        query = MyUsageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        summary = get_usage_summary(request.user, query.validated_data["days"])
        return Response(self.get_serializer(summary).data)


class AvailableModelsView(generics.GenericAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = AvailableAIModelsSerializer

    @extend_schema(responses=AvailableAIModelsSerializer)
    def get(self, request):
        models = list(available_models_for_user(request.user))
        available_ids = {model.model for model in models}
        settings = AIUsageSettings.objects.select_related("default_model", "fallback_model").get(pk=1)
        configured_default = settings.default_model_id
        default_model = (
            configured_default
            if configured_default in available_ids
            else next(
                (model.model for model in models),
                None,
            )
        )
        fallback_model = (
            settings.fallback_model
            if settings.fallback_model and settings.fallback_model.active and settings.fallback_model.deleted_at is None
            else None
        )
        return Response(
            self.get_serializer(
                {
                    "default_model": default_model,
                    "fallback_model": fallback_model,
                    "models": models,
                }
            ).data
        )


class AdminPermissionsView(generics.GenericAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = AdminPermissionsSerializer

    @extend_schema(responses=AdminPermissionsSerializer)
    def get(self, request):
        user = request.user
        permissions = {
            "view_stats": user.is_superuser or user.has_perm("ai.view_ai_usage_stats"),
            "manage_limits": user.is_superuser or user.has_perm("ai.manage_ai_limits"),
        }
        return Response(self.get_serializer(permissions).data)


class ChatListView(generics.ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = AIChatConversationListSerializer
    pagination_class = AIUsagePagination
    queryset = AIChatConversation.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset
        return AIChatConversation.objects.filter(user=self.request.user).select_related("quiz")


class ChatDetailView(generics.RetrieveDestroyAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = AIChatConversationSerializer
    lookup_url_kwarg = "conversation_id"
    queryset = AIChatConversation.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset
        return AIChatConversation.objects.filter(user=self.request.user).prefetch_related("messages__model")


class BulkConfigurationView(generics.GenericAPIView):
    permission_classes = (CanManageAILimits,)
    filter_backends = ()

    def get(self, request):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def put(self, request):
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema_view(
    get=extend_schema(responses=AIAccountLimitSerializer(many=True)),
    put=extend_schema(
        request=AIAccountLimitSerializer(many=True),
        responses=AIAccountLimitSerializer(many=True),
    ),
)
class AdminLimitsView(BulkConfigurationView):
    serializer_class = AIAccountLimitSerializer
    queryset = AIAccountLimit.objects.all()


class AdminLimitsResetView(generics.GenericAPIView):
    permission_classes = (CanManageAILimits,)
    serializer_class = AILimitsResetSerializer

    @extend_schema(request=None, responses=AILimitsResetSerializer)
    def post(self, request):
        return Response(self.get_serializer({"reset_at": reset_all_limits()}).data)


class AdminModelViewSet(viewsets.ModelViewSet):
    permission_classes = (CanManageAILimits,)
    serializer_class = AIModelSerializer
    queryset = AIModel.objects.not_deleted()
    http_method_names = ("get", "post", "put", "patch", "delete", "head", "options")
    lookup_value_regex = r"[^/]+"

    @action(detail=False, methods=("put",), url_path="bulk")
    def bulk(self, request):
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def perform_destroy(self, instance):
        try:
            soft_delete_model(instance)
        except ValueError:
            raise ValidationError({"detail": "Unable to delete this model."}) from None


class AdminSettingsView(generics.RetrieveUpdateAPIView):
    permission_classes = (CanManageAILimits,)
    serializer_class = AIUsageSettingsSerializer
    queryset = AIUsageSettings.objects.all()
    http_method_names = ("get", "put", "head", "options")

    def get_object(self):
        return AIUsageSettings.load()


class AdminUserOverrideView(generics.GenericAPIView):
    permission_classes = (CanManageAILimits,)
    serializer_class = AIUserLimitOverrideSerializer
    queryset = AIUserLimitOverride.objects.all()

    def _user(self, user_id):
        return generics.get_object_or_404(User, pk=user_id)

    @extend_schema(responses=AIUserLimitOverrideResponseSerializer)
    def get(self, request, user_id):
        override = AIUserLimitOverride.objects.filter(user=self._user(user_id)).first()
        return Response(self.get_serializer(override).data if override else {})

    def put(self, request, user_id):
        user = self._user(user_id)
        override = AIUserLimitOverride.objects.filter(user=user).first()
        serializer = self.get_serializer(override, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=user)
        return Response(serializer.data)

    def delete(self, request, user_id):
        AIUserLimitOverride.objects.filter(user=self._user(user_id)).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminUsersView(generics.GenericAPIView):
    permission_classes = (HasAIStatsPermission,)
    serializer_class = AdminUserSerializer
    queryset = User.objects.none()
    filter_backends = ()

    @extend_schema(parameters=[AdminUsersQuerySerializer], responses=AdminUserSerializer(many=True))
    def get(self, request):
        query = AdminUsersQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = get_admin_users(
            query=query.validated_data["q"],
            overrides_only=query.validated_data["overrides_only"],
        )
        return Response(self.get_serializer(rows, many=True).data)


class AdminUserEventsView(generics.ListAPIView):
    permission_classes = (HasAIStatsPermission,)
    serializer_class = AIUsageEventSerializer
    pagination_class = AIUsagePagination
    queryset = AIUsageEvent.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset
        return AIUsageEvent.objects.filter(user_id=self.kwargs["user_id"]).select_related("user", "quiz", "model")


class AdminStatsView(generics.GenericAPIView):
    permission_classes = (HasAIStatsPermission,)
    serializer_class = AdminStatsSerializer

    @extend_schema(parameters=[AdminStatsQuerySerializer], responses=AdminStatsSerializer)
    def get(self, request):
        query = AdminStatsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(self.get_serializer(get_admin_stats(**query.validated_data)).data)


class GenerateQuizView(generics.GenericAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = GenerateQuizFromPDFSerializer
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        request=GenerateQuizFromPDFSerializer,
    )
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        try:
            quiz_json = generate_quiz_from_pdf(
                pdf_file=data["pdf_file"],
                question_count=data["question_count"],
                difficulty=data["difficulty"],
                request_id=data["request_id"],
            )
            return Response(quiz_json, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
