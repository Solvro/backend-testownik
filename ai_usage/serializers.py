from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from .models import (
    AIAccountLimit,
    AIChatConversation,
    AIChatMessage,
    AIModel,
    AIProvider,
    AIUsageEvent,
    AIUsageScope,
    AIUsageSettings,
    AIUserLimitOverride,
)


class CompactDecimalField(serializers.DecimalField):
    def to_representation(self, value):
        if value is None:
            return None
        decimal = Decimal(str(value))
        return format(decimal.normalize(), "f") if decimal else "0"


class BulkUpsertListSerializer(serializers.ListSerializer):
    identity_fields = ()

    def validate(self, attrs):
        seen = set()
        duplicates = set()
        for item in attrs:
            identity = tuple(item[field] for field in self.identity_fields)
            if identity in seen:
                duplicates.add(identity)
            seen.add(identity)
        if duplicates:
            labels = ["/".join(map(str, identity)) for identity in sorted(duplicates)]
            raise serializers.ValidationError(f"Duplicate rows: {', '.join(labels)}.")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        model = self.child.Meta.model
        rows = []
        for item in validated_data:
            lookup = {field: item[field] for field in self.identity_fields}
            defaults = {key: value for key, value in item.items() if key not in self.identity_fields}
            row, _ = model.objects.update_or_create(**lookup, defaults=defaults)
            rows.append(row)
        return rows


class AIAccountLimitListSerializer(BulkUpsertListSerializer):
    identity_fields = ("account_type", "account_level")


class AIAccountLimitSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIAccountLimit
        fields = ("account_type", "account_level", "credits_session", "credits_weekly", "updated_at")
        read_only_fields = ("updated_at",)
        validators = []
        list_serializer_class = AIAccountLimitListSerializer


class AILimitsResetSerializer(serializers.Serializer):
    reset_at = serializers.DateTimeField()


class AIUserLimitOverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIUserLimitOverride
        fields = ("credits_session", "credits_weekly", "note", "created_at", "updated_at")
        read_only_fields = ("created_at", "updated_at")


class AIUserLimitOverrideResponseSerializer(serializers.Serializer):
    credits_session = serializers.IntegerField(min_value=0, allow_null=True, required=False)
    credits_weekly = serializers.IntegerField(min_value=0, allow_null=True, required=False)
    note = serializers.CharField(allow_blank=True, required=False)
    created_at = serializers.DateTimeField(required=False)
    updated_at = serializers.DateTimeField(required=False)


class AIModelListSerializer(BulkUpsertListSerializer):
    identity_fields = ("model",)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        settings = AIUsageSettings.load()
        protected_models = {settings.default_model_id, settings.fallback_model_id}
        if any(item["model"] in protected_models and item.get("active", True) is False for item in attrs):
            raise serializers.ValidationError("Change the default or fallback model before deactivating it.")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        settings = AIUsageSettings.objects.select_for_update().get(pk=1)
        model_ids = [item["model"] for item in validated_data]
        existing_models = {
            model.model: model for model in AIModel.objects.select_for_update().filter(model__in=model_ids)
        }
        unavailable_ids = [
            model_id
            for model_id in model_ids
            if model_id not in existing_models or existing_models[model_id].deleted_at is not None
        ]
        if unavailable_ids:
            raise serializers.ValidationError(
                f"Unknown or deleted models: {', '.join(unavailable_ids)}. Add new models separately."
            )
        protected_models = {settings.default_model_id, settings.fallback_model_id}
        if any(item["model"] in protected_models and item.get("active", True) is False for item in validated_data):
            raise serializers.ValidationError("Change the default or fallback model before deactivating it.")
        rows = []
        for item in validated_data:
            model = existing_models[item["model"]]
            if item["provider"] != model.provider:
                raise serializers.ValidationError(
                    {item["model"]: {"provider": "A model provider cannot be changed after creation."}}
                )
            for field, value in item.items():
                if field not in {"model", "provider"}:
                    setattr(model, field, value)
            model.full_clean()
            model.save()
            rows.append(model)
        return rows


class AIModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIModel
        fields = (
            "model",
            "label",
            "provider",
            "minimum_account_level",
            "input_weight",
            "output_weight",
            "cached_weight",
            "active",
            "updated_at",
        )
        read_only_fields = ("updated_at",)
        extra_kwargs = {"model": {"validators": []}}
        list_serializer_class = AIModelListSerializer

    def validate_model(self, value):
        if (
            self.instance is None
            and not isinstance(self.parent, AIModelListSerializer)
            and AIModel.objects.filter(model=value).exists()
        ):
            raise serializers.ValidationError("A model with this identifier already exists.")
        return value

    def validate(self, attrs):
        active = attrs.get("active", getattr(self.instance, "active", True))
        model = attrs.get("model", getattr(self.instance, "model", None))
        if active is False and model is not None:
            settings = AIUsageSettings.load()
            if model in {settings.default_model_id, settings.fallback_model_id}:
                raise serializers.ValidationError(
                    {"active": "Change the default or fallback model before deactivating it."}
                )
        if self.instance is not None and "model" in attrs and attrs["model"] != self.instance.model:
            raise serializers.ValidationError({"model": "A model identifier cannot be changed after creation."})
        if self.instance is not None and "provider" in attrs and attrs["provider"] != self.instance.provider:
            raise serializers.ValidationError({"provider": "A model provider cannot be changed after creation."})
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        settings = AIUsageSettings.objects.select_for_update().get(pk=1)
        model = AIModel.objects.select_for_update().get(pk=instance.pk)
        if validated_data.get("active", model.active) is False and model.model in {
            settings.default_model_id,
            settings.fallback_model_id,
        }:
            raise serializers.ValidationError(
                {"active": "Change the default or fallback model before deactivating it."}
            )
        return super().update(model, validated_data)


class AIUsageSettingsSerializer(serializers.ModelSerializer):
    default_model = serializers.SlugRelatedField(
        slug_field="model",
        queryset=AIModel.objects.filter(active=True, deleted_at__isnull=True),
    )
    fallback_model = serializers.SlugRelatedField(
        slug_field="model",
        queryset=AIModel.objects.filter(active=True, deleted_at__isnull=True),
        allow_null=True,
    )

    class Meta:
        model = AIUsageSettings
        fields = (
            "limits_enabled",
            "grace_buffer_credits",
            "staff_bypass_limits",
            "default_model",
            "fallback_model",
            "fallback_throttle_seconds",
            "fallback_max_output_tokens",
            "updated_at",
        )
        read_only_fields = ("updated_at",)
        extra_kwargs = {"fallback_max_output_tokens": {"min_value": 16}}

    @transaction.atomic
    def update(self, instance, validated_data):
        settings = AIUsageSettings.objects.select_for_update().get(pk=instance.pk)
        model_ids = {
            model.model
            for model in (
                validated_data.get("default_model", settings.default_model),
                validated_data.get("fallback_model", settings.fallback_model),
            )
            if model is not None
        }
        active_model_ids = set(
            AIModel.objects.select_for_update()
            .filter(model__in=model_ids, active=True, deleted_at__isnull=True)
            .values_list("model", flat=True)
        )
        if active_model_ids != model_ids:
            raise serializers.ValidationError("Select active default and fallback models.")
        return super().update(settings, validated_data)


class AvailableAIModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIModel
        fields = ("model", "label", "provider")


class AvailableAIModelsSerializer(serializers.Serializer):
    default_model = serializers.CharField(allow_null=True)
    fallback_model = AvailableAIModelSerializer(allow_null=True)
    models = AvailableAIModelSerializer(many=True)


class AIUsageEventSerializer(serializers.ModelSerializer):
    provider = serializers.CharField(source="model.provider", read_only=True)

    class Meta:
        model = AIUsageEvent
        fields = (
            "id",
            "user",
            "scope",
            "model",
            "provider",
            "input_tokens",
            "output_tokens",
            "cached_tokens",
            "credits",
            "conversation",
            "quiz",
            "request_id",
            "aborted",
            "finish_reason",
            "error",
            "latency_ms",
            "metadata",
            "quota_exempt",
            "created_at",
        )


class AIChatConversationListSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIChatConversation
        fields = ("id", "quiz", "scope", "title", "created_at", "updated_at")


class AIChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIChatMessage
        fields = ("message_id", "role", "content", "model", "order", "created_at")


class AIChatConversationSerializer(serializers.ModelSerializer):
    messages = AIChatMessageSerializer(many=True, read_only=True)

    class Meta:
        model = AIChatConversation
        fields = ("id", "quiz", "scope", "title", "created_at", "updated_at", "messages")


class InternalQuotaCheckSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    scope = serializers.ChoiceField(choices=AIUsageScope.choices, required=False)
    estimated_input_tokens = serializers.IntegerField(required=False, min_value=0)
    requested_model = serializers.CharField(max_length=100, required=False)
    available_providers = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        max_length=20,
    )


class InternalUsageReportSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    scope = serializers.ChoiceField(choices=AIUsageScope.choices)
    model = serializers.CharField(max_length=100)
    input_tokens = serializers.IntegerField(min_value=0, default=0)
    output_tokens = serializers.IntegerField(min_value=0, default=0)
    cached_tokens = serializers.IntegerField(min_value=0, default=0)
    request_id = serializers.CharField(max_length=100)
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    quiz_id = serializers.UUIDField(required=False, allow_null=True)
    aborted = serializers.BooleanField(default=False)
    finish_reason = serializers.CharField(max_length=100, required=False, allow_blank=True)
    error = serializers.CharField(required=False, allow_blank=True)
    latency_ms = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    fallback_grant_id = serializers.UUIDField(required=False, allow_null=True)
    metadata = serializers.DictField(required=False)
    messages = serializers.ListField(child=serializers.DictField(), required=False, max_length=500)


class MyUsageQuerySerializer(serializers.Serializer):
    days = serializers.IntegerField(default=30, min_value=7, max_value=30)


class AdminStatsQuerySerializer(serializers.Serializer):
    days = serializers.IntegerField(default=30, min_value=1, max_value=365)


class AdminUsersQuerySerializer(serializers.Serializer):
    q = serializers.CharField(default="", allow_blank=True, trim_whitespace=True, max_length=200)
    overrides_only = serializers.BooleanField(default=False)


class AIUsageWindowSerializer(serializers.Serializer):
    used = CompactDecimalField(max_digits=20, decimal_places=6)
    limit = CompactDecimalField(max_digits=20, decimal_places=6, allow_null=True)
    remaining = CompactDecimalField(max_digits=20, decimal_places=6, allow_null=True)
    resets_at = serializers.DateTimeField(allow_null=True)


class AIUsageBreakdownSerializer(serializers.Serializer):
    model = serializers.CharField(required=False)
    scope = serializers.CharField(required=False)
    credits = CompactDecimalField(max_digits=20, decimal_places=6)
    events = serializers.IntegerField(min_value=0)


class AIModelUsageBreakdownSerializer(serializers.Serializer):
    model = serializers.CharField()
    label = serializers.CharField()
    provider = serializers.ChoiceField(choices=AIProvider.choices)
    credits = CompactDecimalField(max_digits=20, decimal_places=6)
    events = serializers.IntegerField(min_value=0)


class AIUsageDailySerializer(serializers.Serializer):
    date = serializers.DateField()
    credits = CompactDecimalField(max_digits=20, decimal_places=6)
    events = serializers.IntegerField(min_value=0)


class AIUsageSummarySerializer(serializers.Serializer):
    session = AIUsageWindowSerializer()
    weekly = AIUsageWindowSerializer()
    limits_enabled = serializers.BooleanField()
    exhausted = serializers.BooleanField()
    blocked_until = serializers.DateTimeField(allow_null=True)
    fallback_resets_at = serializers.DateTimeField(allow_null=True)
    active_models = serializers.ListField(child=serializers.CharField())
    fallback_model = serializers.CharField(allow_null=True)
    daily = AIUsageDailySerializer(many=True)
    by_model = AIUsageBreakdownSerializer(many=True)
    by_scope = AIUsageBreakdownSerializer(many=True)


class QuotaUsageSerializer(serializers.Serializer):
    session = AIUsageWindowSerializer()
    weekly = AIUsageWindowSerializer()


class QuotaDecisionSerializer(serializers.Serializer):
    allowed = serializers.BooleanField()
    would_block = serializers.BooleanField()
    limits_enabled = serializers.BooleanField()
    exceeded_window = serializers.ChoiceField(
        choices=("session", "weekly", "input", "fallback_throttle", "model_unavailable"),
        allow_null=True,
    )
    resets_at = serializers.DateTimeField(allow_null=True)
    usage = QuotaUsageSerializer()
    suggested_max_output_tokens = serializers.IntegerField(min_value=1)
    quota_tier = serializers.ChoiceField(choices=("normal", "fallback"))
    fallback_model = serializers.CharField(allow_null=True)
    fallback_grant_id = serializers.UUIDField(allow_null=True)
    fallback_resets_at = serializers.DateTimeField(allow_null=True)
    resolved_model = serializers.CharField(allow_null=True)
    resolved_provider = serializers.CharField(allow_null=True)
    active_models = serializers.ListField(child=serializers.CharField())


class UsageReportResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    credits = CompactDecimalField(max_digits=18, decimal_places=6)
    created = serializers.BooleanField()


class AdminPermissionsSerializer(serializers.Serializer):
    view_stats = serializers.BooleanField()
    manage_limits = serializers.BooleanField()


class AdminUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField(allow_null=True)
    name = serializers.CharField(allow_blank=True)
    account_type = serializers.CharField(allow_null=True)
    account_level = serializers.CharField(allow_null=True)
    has_override = serializers.BooleanField()
    usage = AIUsageSummarySerializer()


class AdminStatsTotalsSerializer(serializers.Serializer):
    credits = CompactDecimalField(max_digits=20, decimal_places=6)
    input_tokens = serializers.IntegerField(min_value=0)
    output_tokens = serializers.IntegerField(min_value=0)
    cached_tokens = serializers.IntegerField(min_value=0)
    events = serializers.IntegerField(min_value=0)
    aborted = serializers.IntegerField(min_value=0)
    errors = serializers.IntegerField(min_value=0)


class AdminStatsDailySerializer(serializers.Serializer):
    day = serializers.DateField()
    credits = CompactDecimalField(max_digits=20, decimal_places=6)
    events = serializers.IntegerField(min_value=0)


class AdminStatsTopUserSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    user__email = serializers.EmailField(allow_null=True)
    credits = CompactDecimalField(max_digits=20, decimal_places=6)
    events = serializers.IntegerField(min_value=0)


class AdminStatsSerializer(serializers.Serializer):
    totals = AdminStatsTotalsSerializer()
    by_model = AIModelUsageBreakdownSerializer(many=True)
    by_scope = AIUsageBreakdownSerializer(many=True)
    top_users = AdminStatsTopUserSerializer(many=True)
    daily = AdminStatsDailySerializer(many=True)
    limits_enabled = serializers.BooleanField()
