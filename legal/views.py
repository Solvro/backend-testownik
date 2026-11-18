from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LegalAcceptance, LegalDocumentKind, LegalDocumentVersion, pending_version_for
from .serializers import (
    LegalAcceptanceCreateSerializer,
    LegalDocumentSerializer,
    LegalDocumentVersionSerializer,
    LegalDocumentVersionSummarySerializer,
    PendingNoticesSerializer,
)


def _kind(value):
    if value not in LegalDocumentKind.values:
        raise Http404
    return value


class LegalDocumentView(APIView):
    """The version of a document in force now, plus the next one if it's already announced."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(summary="Get the current terms or privacy policy", responses=LegalDocumentSerializer)
    def get(self, request, kind):
        kind = _kind(kind)
        versions = LegalDocumentVersion.objects
        data = {"current": versions.current(kind), "upcoming": versions.upcoming(kind)}
        return Response(LegalDocumentSerializer(data).data)


class LegalDocumentVersionListView(APIView):
    """Every published version, newest first, for the archive."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(summary="List published versions", responses=LegalDocumentVersionSummarySerializer(many=True))
    def get(self, request, kind):
        versions = LegalDocumentVersion.objects.published().filter(kind=_kind(kind)).order_by("-version")
        return Response(LegalDocumentVersionSummarySerializer(versions, many=True).data)


class LegalDocumentVersionDetailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(summary="Get one published version", responses=LegalDocumentVersionSerializer)
    def get(self, request, kind, version):
        document = get_object_or_404(LegalDocumentVersion.objects.published(), kind=_kind(kind), version=version)
        return Response(LegalDocumentVersionSerializer(document).data)


class PendingNoticesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Get the versions the user still has to confirm", responses=PendingNoticesSerializer)
    def get(self, request):
        pending = {kind: pending_version_for(request.user, kind) for kind in LegalDocumentKind.values}
        return Response(PendingNoticesSerializer(pending).data)


class LegalAcceptanceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Confirm document versions",
        request=LegalAcceptanceCreateSerializer,
        responses={204: None},
    )
    def post(self, request):
        serializer = LegalAcceptanceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        confirmations = [
            LegalAcceptance(user=request.user, version=version) for version in serializer.validated_data["versions"]
        ]
        LegalAcceptance.objects.bulk_create(confirmations, ignore_conflicts=True)
        return Response(status=status.HTTP_204_NO_CONTENT)
