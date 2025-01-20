from rest_framework import serializers

from users.models import StudyGroup, Term, User, UserSettings


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


class PublicUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name", "student_number", "photo_url"]


class UserSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSettings
        fields = [
            "sync_progress",
            "initial_reoccurrences",
            "wrong_answer_reoccurrences",
        ]


class TermSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = ["id", "name", "start_date", "end_date", "is_current"]


class StudyGroupSerializer(serializers.ModelSerializer):
    term = TermSerializer()

    class Meta:
        model = StudyGroup
        fields = ["id", "name", "term"]
