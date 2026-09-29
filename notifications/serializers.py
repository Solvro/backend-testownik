from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "content",
            "link",
            "is_read",
            "notification_type",
            "delivery_status",
            "created_at",
            "updated_at",
            "user",
        ]
        read_only_fields = [
            "id",
            "title",
            "content",
            "link",
            "notification_type",
            "delivery_status",
            "created_at",
            "updated_at",
            "user",
        ]
