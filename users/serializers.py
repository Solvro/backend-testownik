from rest_framework import serializers

from users.models import StudyGroup, User, UserSettings


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "is_superuser",
            "is_staff",
            "student_number",
            "photo_url",
        ]


class UserSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSettings
        fields = ["sync_progress", "initial_repetitions", "wrong_answer_repetitions"]
