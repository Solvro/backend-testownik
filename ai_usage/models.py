import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from users.models import AccountLevel, AccountType


class AIUsageScope(models.TextChoices):
    CHAT = "chat", "Chat"
    EXPLAIN = "explain", "Explanation"
    HINT = "hint", "Hint"
    QUIZ_GENERATION = "quiz_generation", "Quiz generation"
    ADJUSTMENT = "adjustment", "Adjustment"


class AIProvider(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    ANTHROPIC = "anthropic", "Anthropic"
    XAI = "xai", "xAI"


class AIModelQuerySet(models.QuerySet):
    def not_deleted(self):
        return self.filter(deleted_at__isnull=True)

    def available_for_account_level(self, account_level):
        allowed_levels = {
            AccountLevel.BASIC: (AccountLevel.BASIC,),
            AccountLevel.SILVER: (AccountLevel.BASIC, AccountLevel.SILVER),
            AccountLevel.GOLD: (AccountLevel.BASIC, AccountLevel.SILVER, AccountLevel.GOLD),
        }
        return self.not_deleted().filter(
            active=True,
            minimum_account_level__in=allowed_levels.get(account_level, (AccountLevel.BASIC,)),
        )


class AIAccountLimit(models.Model):
    account_type = models.CharField(max_length=10, choices=AccountType.choices)
    account_level = models.CharField(max_length=10, choices=AccountLevel.choices)
    credits_session = models.PositiveBigIntegerField(null=True, blank=True)
    credits_weekly = models.PositiveBigIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("account_type", "account_level"), name="unique_ai_account_limit")
        ]
        ordering = ("account_type", "account_level")

    def __str__(self):
        return f"{self.account_type}/{self.account_level}"


class AIUserLimitOverride(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_limit_override")
    credits_session = models.PositiveBigIntegerField(null=True, blank=True)
    credits_weekly = models.PositiveBigIntegerField(null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.user)


class AIModel(models.Model):
    model = models.CharField(max_length=100, primary_key=True)
    label = models.CharField(max_length=100)
    provider = models.CharField(max_length=20, choices=AIProvider.choices)
    minimum_account_level = models.CharField(
        max_length=10,
        choices=AccountLevel.choices,
        default=AccountLevel.BASIC,
    )
    input_weight = models.DecimalField(max_digits=12, decimal_places=6, validators=[MinValueValidator(0)])
    output_weight = models.DecimalField(max_digits=12, decimal_places=6, validators=[MinValueValidator(0)])
    cached_weight = models.DecimalField(max_digits=12, decimal_places=6, validators=[MinValueValidator(0)])
    active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AIModelQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "AI models"
        ordering = ("provider", "model")

    def __str__(self):
        return self.label

    def clean(self):
        super().clean()
        if (not self.active or self.deleted_at is not None) and AIUsageSettings.objects.filter(
            models.Q(default_model_id=self.model) | models.Q(fallback_model_id=self.model)
        ).exists():
            raise ValidationError({"active": "Change the default or fallback model before disabling it."})


class AIUsageSettings(models.Model):
    limits_enabled = models.BooleanField(default=False)
    grace_buffer_credits = models.DecimalField(
        max_digits=14, decimal_places=4, default=2000, validators=[MinValueValidator(0)]
    )
    staff_bypass_limits = models.BooleanField(default=True)
    default_model = models.ForeignKey(
        AIModel,
        on_delete=models.PROTECT,
        related_name="default_for_settings",
    )
    fallback_model = models.ForeignKey(
        AIModel,
        on_delete=models.SET_NULL,
        related_name="fallback_for_settings",
        null=True,
        blank=True,
    )
    fallback_throttle_seconds = models.PositiveIntegerField(default=15)
    fallback_max_output_tokens = models.PositiveIntegerField(
        default=500,
        validators=[MinValueValidator(16)],
    )
    limits_reset_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "AI usage settings"

    def __str__(self):
        return "AI usage settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not AIModel.objects.filter(model=self.default_model_id, active=True, deleted_at__isnull=True).exists():
            raise ValidationError({"default_model": "Select an active default model."})
        if (
            self.fallback_model_id
            and not AIModel.objects.filter(
                model=self.fallback_model_id,
                active=True,
                deleted_at__isnull=True,
            ).exists()
        ):
            raise ValidationError({"fallback_model": "Select an active fallback model."})

    @classmethod
    def load(cls):
        return cls.objects.select_related("default_model", "fallback_model").get(pk=1)


class AIChatConversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_chat_conversations")
    quiz = models.ForeignKey(
        "quizzes.Quiz", on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_chat_conversations"
    )
    scope = models.CharField(max_length=40, choices=AIUsageScope.choices, default=AIUsageScope.CHAT)
    title = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        permissions = [
            ("view_ai_usage_stats", "Can view AI usage statistics"),
            ("manage_ai_limits", "Can manage AI limits"),
        ]

    def __str__(self):
        return self.title or str(self.id)


class AIChatMessage(models.Model):
    conversation = models.ForeignKey(AIChatConversation, on_delete=models.CASCADE, related_name="messages")
    message_id = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=20)
    content = models.JSONField(default=list)
    model = models.ForeignKey(
        AIModel,
        on_delete=models.PROTECT,
        related_name="chat_messages",
        null=True,
        blank=True,
    )
    order = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("order", "id")
        constraints = [models.UniqueConstraint(fields=("conversation", "order"), name="unique_ai_chat_message_order")]

    def __str__(self):
        return f"{self.conversation_id}:{self.order}"


class AIUsageEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_usage_events")
    scope = models.CharField(max_length=40, choices=AIUsageScope.choices)
    model = models.ForeignKey(AIModel, on_delete=models.PROTECT, related_name="usage_events")
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    cached_tokens = models.PositiveBigIntegerField(default=0)
    credits = models.DecimalField(max_digits=18, decimal_places=6)
    conversation = models.ForeignKey(
        AIChatConversation, on_delete=models.SET_NULL, null=True, blank=True, related_name="usage_events"
    )
    quiz = models.ForeignKey(
        "quizzes.Quiz", on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_usage_events"
    )
    request_id = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    aborted = models.BooleanField(default=False)
    finish_reason = models.CharField(max_length=100, blank=True, default="")
    error = models.TextField(blank=True, default="")
    latency_ms = models.PositiveBigIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    quota_exempt = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("user", "created_at"), name="ai_usage_user_created_idx"),
            models.Index(fields=("created_at",), name="ai_usage_created_idx"),
            models.Index(fields=("scope", "created_at"), name="ai_usage_scope_created_idx"),
            models.Index(fields=("model", "created_at"), name="ai_usage_model_created_idx"),
            models.Index(
                fields=("user", "quota_exempt", "created_at"),
                name="ai_usage_quota_window_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.scope}:{self.created_at}"

    @property
    def provider(self):
        return self.model.provider


class AIFallbackGrant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_fallback_grants",
    )
    model = models.ForeignKey(AIModel, on_delete=models.PROTECT, related_name="fallback_grants")
    issued_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-issued_at",)
        indexes = [
            models.Index(
                fields=("user", "issued_at"),
                name="ai_fallback_grant_user_idx",
            )
        ]

    def __str__(self):
        return f"{self.user_id}:{self.model_id}:{self.issued_at}"


class AIUsageDailyAggregate(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_usage_daily_aggregates"
    )
    date = models.DateField()
    scope = models.CharField(max_length=40, choices=AIUsageScope.choices)
    model = models.ForeignKey(AIModel, on_delete=models.PROTECT, related_name="daily_aggregates")
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    cached_tokens = models.PositiveBigIntegerField(default=0)
    credits = models.DecimalField(max_digits=20, decimal_places=6, default=0)
    event_count = models.PositiveBigIntegerField(default=0)
    aborted_count = models.PositiveBigIntegerField(default=0)
    error_count = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "date", "scope", "model"), name="unique_ai_daily_aggregate")
        ]
        indexes = [models.Index(fields=("date",), name="ai_daily_date_idx")]

    def __str__(self):
        return f"{self.user_id}:{self.date}:{self.scope}:{self.model_id}"
