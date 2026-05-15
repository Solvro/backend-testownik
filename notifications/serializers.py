from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "content", "is_read", "user"]
        read_only_fields = ["id", "title", "content", "user"]
