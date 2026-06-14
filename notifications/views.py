from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    ViewSet for managing user notifications.

    This ViewSet allows authenticated frontend users to read and manage their notifications.
    Notifications are created by other apps via :func:`notifications.utils.send_notification`
    and this endpoint provides read-only access (with the ability to mark them as read).

    Available actions:
    - GET: Retrieve user's notifications
    - PATCH: Update notification status (mark as read)
    - mark-all-read: Custom action to mark all unread notifications as read
    """

    # We override get_queryset to filter by user, so we start with an empty queryset here.
    queryset = Notification.objects.none()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_read", "created_at", "notification_type"]

    # Disable full updates (PUT) — only partial updates (PATCH) are supported.
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=False, methods=["patch"], url_path="mark-all-read")
    def mark_all_read(self, request):
        updated_count = self.get_queryset().filter(is_read=False).update(is_read=True, updated_at=timezone.now())

        return Response(
            {
                "message": f"{updated_count} notifications marked as read",
            },
            status=status.HTTP_200_OK,
        )
