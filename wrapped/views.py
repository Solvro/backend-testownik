from constance import config as constance_config
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from wrapped import config
from wrapped.models import WrappedReport


def _no_activity_payload(term, *, is_global: bool = False) -> dict:
    """Shown when a user has no activity in the (current) term."""
    return {
        "is_empty": True,
        "is_global": is_global,
        "season": config.season_block(term) if term is not None else None,
    }


@extend_schema(
    summary="Get Testownik Wrapped",
    description="Returns the current user's latest Wrapped report. Gated by the "
    "WRAPPED_ENABLED constance flag; returns the empty state when the user has no "
    "activity in the current term.",
)
@api_view(["GET"])
def get_wrapped(request: Request) -> Response:
    if not constance_config.WRAPPED_ENABLED:
        return Response({"detail": "Wrapped is not available."}, status=404)

    report = (
        WrappedReport.objects.filter(user=request.user, is_global=False)
        .select_related("term")
        .prefetch_related("top_quizzes")
        .order_by("-term__finish_date")
        .first()
    )
    if report is not None:
        return Response(report.to_payload())

    return Response(_no_activity_payload(config.select_term()))


@extend_schema(
    summary="Get global Testownik Wrapped",
    description="Platform-wide Wrapped for the latest term (all users, guests included).",
)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def get_wrapped_global(request: Request) -> Response:
    if not constance_config.WRAPPED_ENABLED:
        return Response({"detail": "Wrapped is not available."}, status=404)

    report = (
        WrappedReport.objects.filter(is_global=True)
        .select_related("term")
        .prefetch_related("top_quizzes")
        .order_by("-term__finish_date")
        .first()
    )
    if report is not None:
        return Response(report.to_payload())

    return Response(_no_activity_payload(config.select_term(), is_global=True))
