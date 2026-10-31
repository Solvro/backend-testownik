import logging

from django.contrib import admin, messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from ..account_levels import grant_account_level
from ..models import AccountLevelGrant, AccountLevelGrantSource, User
from ..permissions import CanManageAccountLevels
from ..serializers import AccountLevelGrantCreateSerializer, AccountLevelGrantSerializer
from .utils import is_safe_redirect_url

logger = logging.getLogger(__name__)


def admin_login(request):
    next_url = request.GET.get("next", "admin:index")
    if not is_safe_redirect_url(next_url, request):
        logger.warning("Blocked unsafe redirect URL in admin_login: %s", next_url)
        messages.error(request, "Unsafe redirect URL, defaulting to admin index")
        next_url = "admin:index"
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect(next_url)

    usos_login_url = reverse("login_usos") + f"?redirect={next_url}"
    solvro_login_url = reverse("login") + f"?redirect={next_url}"

    context = {
        **admin.site.each_context(request),
        "next": next_url,
        "username": request.user,
        "usos_login_url": usos_login_url,
        "solvro_login_url": solvro_login_url,
        "usos_login_url_confirm": usos_login_url + "&confirm_user=true",
        "solvro_login_url_confirm": solvro_login_url + "&confirm_user=true",
    }

    return render(request, "users/admin_login.html", context)


class AccountLevelGrantPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100


class AccountLevelAdminPermissionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Check account level admin permissions",
        responses={200: {"type": "object", "properties": {"can_manage_account_levels": {"type": "boolean"}}}},
    )
    def get(self, request):
        return Response(
            {
                "can_manage_account_levels": request.user.has_perm("users.manage_account_levels")
                or request.user.is_superuser
            }
        )


class UserAccountLevelGrantViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    permission_classes = [CanManageAccountLevels]
    serializer_class = AccountLevelGrantSerializer
    pagination_class = AccountLevelGrantPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AccountLevelGrant.objects.none()
        get_object_or_404(User, pk=self.kwargs["user_pk"])
        return (
            AccountLevelGrant.objects.filter(user_id=self.kwargs["user_pk"])
            .select_related("created_by")
            .order_by("-created_at")
        )

    @extend_schema(summary="List user's account level grants")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Grant account level to user",
        request=AccountLevelGrantCreateSerializer,
        responses={201: AccountLevelGrantSerializer},
    )
    def create(self, request, *args, **kwargs):
        user = get_object_or_404(User, pk=self.kwargs["user_pk"])
        serializer = AccountLevelGrantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            grant = grant_account_level(
                user=user,
                level=serializer.validated_data["level"],
                source=AccountLevelGrantSource.ADMIN,
                indefinite=serializer.validated_data.get("indefinite", False),
                duration_months=serializer.validated_data.get("duration_months"),
                duration_days=serializer.validated_data.get("duration_days"),
                expires_at=serializer.validated_data.get("expires_at"),
                created_by=request.user,
                reason=serializer.validated_data.get("reason", ""),
            )
        except DjangoValidationError as exc:
            raise DRFValidationError(getattr(exc, "message_dict", exc.messages)) from exc
        return Response(AccountLevelGrantSerializer(grant).data, status=201)


class AccountLevelGrantViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [CanManageAccountLevels]
    serializer_class = AccountLevelGrantSerializer
    lookup_url_kwarg = "grant_id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AccountLevelGrant.objects.none()
        get_object_or_404(User, pk=self.kwargs["user_pk"])
        return AccountLevelGrant.objects.filter(user_id=self.kwargs["user_pk"]).select_related("created_by")

    @extend_schema(summary="Get account level grant details")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
