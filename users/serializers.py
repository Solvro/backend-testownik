from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken

from ai.models import AIModel
from users.account_levels import (
    MAX_DURATION_DAYS,
    MAX_DURATION_MONTHS,
    get_account_level_state,
    get_effective_account_level,
)
from users.models import AccountLevel, AccountLevelGrant, StudyGroup, Term, User, UserSettings


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
        token["account_level"] = get_effective_account_level(user).value

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


class AccountLevelDetailsSerializer(serializers.Serializer):
    effective_level = serializers.ChoiceField(choices=AccountLevel.choices)
    permanent_level = serializers.ChoiceField(choices=AccountLevel.choices)
    expires_at = serializers.DateTimeField(allow_null=True)
    next_level = serializers.ChoiceField(choices=AccountLevel.choices, allow_null=True)


class UserSerializer(serializers.ModelSerializer):
    has_custom_photo = serializers.SerializerMethodField()
    default_photo = serializers.URLField(read_only=True, allow_null=True)
    account_level_details = serializers.SerializerMethodField()
    account_level = serializers.SerializerMethodField()

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
            "default_photo",
            "has_custom_photo",
            "hide_profile",
            "account_type",
            "account_level",
            "account_level_details",
        ]

    @extend_schema_field(serializers.CharField())
    def get_account_level(self, obj: User) -> str:
        return self._get_account_level_state(obj).effective_level.value

    @extend_schema_field(AccountLevelDetailsSerializer)
    def get_account_level_details(self, obj: User) -> dict:
        state = self._get_account_level_state(obj)
        return AccountLevelDetailsSerializer(
            {
                "effective_level": state.effective_level,
                "permanent_level": state.permanent_level,
                "expires_at": state.expires_at,
                "next_level": state.next_level,
            }
        ).data

    def _get_account_level_state(self, obj: User):
        state = getattr(self, "_account_level_state", None)
        if state is None or self._account_level_state_user_id != obj.pk:
            state = get_account_level_state(obj)
            self._account_level_state = state
            self._account_level_state_user_id = obj.pk
        return state

    def get_has_custom_photo(self, obj):
        return obj.custom_photo_image_id is not None or bool(obj.overriden_photo_url)


class PublicUserSerializer(serializers.ModelSerializer):
    account_level = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "student_number", "photo", "account_type", "account_level"]

    @extend_schema_field(serializers.CharField())
    def get_account_level(self, obj: User) -> str:
        return get_effective_account_level(obj).value


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
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            raise serializers.ValidationError("Select an active model available for your account.")

        effective_level = get_effective_account_level(user)
        if not AIModel.objects.available_for_account_level(effective_level).filter(pk=value.pk).exists():
            raise serializers.ValidationError("Select an active model available for your account.")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        selected_model = validated_data.get("default_ai_model")
        if selected_model is not None:
            effective_level = get_effective_account_level(self.context["request"].user)
            selected_model = (
                AIModel.objects.select_for_update()
                .available_for_account_level(effective_level)
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


class TimezoneAwareDateTimeField(serializers.DateTimeField):
    def enforce_timezone(self, value):
        if timezone.is_naive(value):
            raise serializers.ValidationError("Datetime must include a timezone.")
        return super().enforce_timezone(value)


class AccountLevelGrantSerializer(serializers.ModelSerializer):
    """
    Serializes a single account level grant for the admin panel list and detail views.
    """

    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)

    class Meta:
        model = AccountLevelGrant
        fields = [
            "id",
            "level",
            "source",
            "source_ref",
            "reason",
            "starts_at",
            "expires_at",
            "created_at",
            "created_by",
            "created_by_email",
        ]
        read_only_fields = fields


class AccountLevelGrantCreateSerializer(serializers.Serializer):
    """
    Validates input for creating a new account level grant via the admin API.
    """

    level = serializers.ChoiceField(
        choices=[
            (AccountLevel.SILVER, AccountLevel.SILVER.label),
            (AccountLevel.GOLD, AccountLevel.GOLD.label),
        ]
    )
    indefinite = serializers.BooleanField(default=False, required=False)
    duration_months = serializers.IntegerField(
        min_value=1, max_value=MAX_DURATION_MONTHS, required=False, allow_null=True
    )
    duration_days = serializers.IntegerField(min_value=1, max_value=MAX_DURATION_DAYS, required=False, allow_null=True)
    expires_at = TimezoneAwareDateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate(self, attrs):
        time_modes = [
            attrs.get("indefinite", False),
            attrs.get("duration_months") is not None,
            attrs.get("duration_days") is not None,
            attrs.get("expires_at") is not None,
        ]
        if sum(time_modes) != 1:
            raise serializers.ValidationError(
                "Exactly one expiry mode must be specified: indefinite, duration_months, duration_days, or expires_at."
            )
        return attrs
