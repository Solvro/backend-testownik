from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken

from ai.models import AIModel
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
        token["sex"] = user.sex
        token["gender"] = user.gender
        token["photo"] = user.photo
        token["is_staff"] = user.is_staff
        token["is_superuser"] = user.is_superuser
        token["is_banned"] = user.is_banned
        token["account_type"] = user.account_type
        token["account_level"] = user.account_level

        return token

    def validate(self, attrs):
        email = attrs.get("email")
        if email:
            user = User.objects.filter(email=email).first()
            if user and user.is_banned:
                raise InvalidToken(
                    {
                        "code": "user_banned",
                        "detail": "Your account has been banned.",
                        "ban_reason": user.ban_reason or "No reason provided",
                    }
                )

        return super().validate(attrs)


class UserTokenRefreshSerializer(TokenRefreshSerializer):
    """Custom JWT refresh serializer that re-populates user data when refreshing tokens."""

    def validate(self, attrs):
        refresh = RefreshToken(attrs["refresh"])
        user_id = refresh.payload.get("user_id")

        if user_id:
            try:
                user = User.objects.select_related("photo_image", "custom_photo_image").get(pk=user_id)
                if user.is_banned:
                    raise InvalidToken(
                        {
                            "code": "user_banned",
                            "detail": "Your account has been banned.",
                            "ban_reason": user.ban_reason or "No reason provided",
                        }
                    )
            except User.DoesNotExist:
                pass

        try:
            data = super().validate(attrs)
        except User.DoesNotExist:
            raise InvalidToken("User associated with this token no longer exists")

        if user_id:
            try:
                user = User.objects.select_related("photo_image", "custom_photo_image").get(pk=user_id)
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
    has_custom_photo = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "is_superuser",
            "is_staff",
            "student_number",
            "sex",
            "gender",
            "photo",
            "has_custom_photo",
            "hide_profile",
            "account_type",
            "account_level",
        ]

    def get_has_custom_photo(self, obj):
        return obj.custom_photo_image_id is not None or bool(obj.overriden_photo_url)


class PublicUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name", "student_number", "photo", "account_type", "account_level"]


class UserSettingsSerializer(serializers.ModelSerializer):
    default_ai_model = serializers.SlugRelatedField(
        slug_field="model",
        queryset=AIModel.objects.filter(active=True, deleted_at__isnull=True),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = UserSettings
        fields = [
            "sync_progress",
            "initial_reoccurrences",
            "wrong_answer_reoccurrences",
            "ai_disabled",
            "default_ai_model",
            "notify_quiz_shared",
            "notify_bug_reported",
            "notify_marketing",
            "max_question_reoccurrences",
        ]

    def validate_initial_reoccurrences(self, value):
        if value < 1:
            raise serializers.ValidationError("Initial repetitions must be ≥ 1")
        return value

    def validate_wrong_answer_reoccurrences(self, value):
        if value < 0:
            raise serializers.ValidationError("Wrong answer repetitions must be ≥ 0")
        return value

    def validate_default_ai_model(self, value):
        if value is None:
            return None
        request = self.context.get("request")
        if (
            request is None
            or not AIModel.objects.available_for_account_level(request.user.account_level).filter(pk=value.pk).exists()
        ):
            raise serializers.ValidationError("Select an active model available for your account.")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        selected_model = validated_data.get("default_ai_model")
        if selected_model is not None:
            selected_model = (
                AIModel.objects.select_for_update()
                .available_for_account_level(self.context["request"].user.account_level)
                .filter(pk=selected_model.pk)
                .first()
            )
            if selected_model is None:
                raise serializers.ValidationError(
                    {"default_ai_model": "Select an active model available for your account."}
                )
            validated_data["default_ai_model"] = selected_model
        return super().update(instance, validated_data)


class TermSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = ["id", "name", "start_date", "end_date", "finish_date", "is_current"]


class StudyGroupSerializer(serializers.ModelSerializer):
    term = TermSerializer()

    class Meta:
        model = StudyGroup
        fields = ["id", "name", "term"]
