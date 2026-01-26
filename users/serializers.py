from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import StudyGroup, Term, User, UserSettings


class UserTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom JWT token serializer that includes user data in the token."""

    @classmethod
    def get_token(cls, user: User):
        token = super().get_token(user)

        token["first_name"] = user.first_name
        token["last_name"] = user.last_name
        token["full_name"] = user.full_name
        token["email"] = user.email
        token["student_number"] = user.student_number
        token["photo"] = user.photo
        token["is_staff"] = user.is_staff
        token["is_superuser"] = user.is_superuser

        return token


class UserTokenRefreshSerializer(TokenRefreshSerializer):
    """Custom JWT refresh serializer that re-populates user data when refreshing tokens."""

    def validate(self, attrs):
        try:
            data = super().validate(attrs)
        except User.DoesNotExist:
            raise InvalidToken("User associated with this token no longer exists")

        refresh = RefreshToken(attrs["refresh"])
        user_id = refresh.payload.get("user_id")

        if user_id:
            try:
                user = User.objects.get(pk=user_id)
                new_access = UserTokenObtainPairSerializer.get_token(user).access_token
                data["access"] = str(new_access)
            except User.DoesNotExist:
                raise InvalidToken("User associated with this token no longer exists")

        return data


class CurrentUserDefault:
    """Default class that returns the currently authenticated user."""

    requires_context = True

    def __call__(self, serializer_field):
        request = serializer_field.context.get("request") if serializer_field.context else None
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            raise serializers.ValidationError("Authenticated user is required.")
        return user


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
            "overriden_photo_url",
            "photo",
            "hide_profile",
        ]


class PublicUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name", "student_number", "photo"]


class UserSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSettings
        fields = [
            "sync_progress",
            "initial_reoccurrences",
            "wrong_answer_reoccurrences",
            "notify_quiz_shared",
            "notify_bug_reported",
            "notify_marketing",
            "max_question_repetitions",
        ]

    def validate_initial_reoccurrences(self, value):
        if value < 1:
            raise serializers.ValidationError("Initial repetitions must be ≥ 1")
        return value

    def validate_wrong_answer_reoccurrences(self, value):
        if value < 0:
            raise serializers.ValidationError("Wrong answer repetitions must be ≥ 0")
        return value


class TermSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = ["id", "name", "start_date", "end_date", "finish_date", "is_current"]


class StudyGroupSerializer(serializers.ModelSerializer):
    term = TermSerializer()

    class Meta:
        model = StudyGroup
        fields = ["id", "name", "term"]
