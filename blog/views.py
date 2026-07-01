from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import AllowAny

from .models import BlogPost
from .serializers import BlogPostDetailSerializer, BlogPostListSerializer


@extend_schema_view(
    list=extend_schema(
        summary="List published blog posts",
        parameters=[
            OpenApiParameter(
                name="recent",
                type=int,
                description="Only return posts published within the last N days (used by the dashboard card).",
                required=False,
            ),
        ],
    ),
    retrieve=extend_schema(summary="Retrieve a single published blog post by slug"),
)
class BlogPostViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Public, read-only access to published blog posts.

    Only posts that are published and whose `published_at` is in the past are
    exposed, which supports scheduled publishing. No authentication required.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = LimitOffsetPagination
    lookup_field = "slug"

    def get_serializer_class(self):
        if self.action == "retrieve":
            return BlogPostDetailSerializer
        return BlogPostListSerializer

    def get_queryset(self):
        queryset = BlogPost.objects.filter(
            is_published=True,
            published_at__lte=timezone.now(),
        ).select_related("author")

        recent = self.request.query_params.get("recent")
        if recent is not None:
            cutoff = timezone.now() - timedelta(days=self._parse_recent(recent))
            queryset = queryset.filter(published_at__gte=cutoff)

        return queryset

    @staticmethod
    def _parse_recent(value):
        try:
            days = int(value)
        except (TypeError, ValueError):
            raise ValidationError({"recent": "Must be a positive integer."})
        if days <= 0:
            raise ValidationError({"recent": "Must be a positive integer."})
        return days
