from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification
from .serializers import NotificationSerializer


# Create your views here.
class NotificationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing user notifications.

    This ViewSet allows authenticated frontend users to read and manage their notifications.
    Notifications are created by other apps and this endpoint provides read-only access
    (with the ability to mark them as read).

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

    # Only allow read and partial update
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        return Notification.objects.filter(user=user)

    @action(detail=False, methods=["patch"], url_path="mark-all-read")
    def mark_all_read(self, request):
        updated_count = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)

        return Response(
            {
                "message": f"{updated_count} notifications marked as read",
            },
            status=status.HTTP_200_OK,
        )
