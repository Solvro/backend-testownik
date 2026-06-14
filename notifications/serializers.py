from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "content",
            "is_read",
            "notification_type",
            "delivery_status",
            "delivery_error",
            "created_at",
            "user",
        ]
        read_only_fields = [
            "id",
            "title",
            "content",
            "notification_type",
            "delivery_status",
            "delivery_error",
            "created_at",
            "user",
        ]
