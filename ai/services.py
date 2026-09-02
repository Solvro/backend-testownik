from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from quizzes.services.operations import QuizOperationError, get_readable_quiz
from users.models import AccountLevel, AccountType, UserSettings

from .models import (
    AIAccountLimit,
    AIChatConversation,
    AIChatMessage,
    AIFallbackGrant,
    AIModel,
    AIUsageEvent,
    AIUsageScope,
    AIUsageSettings,
    AIUserLimitOverride,
)
from .quiz_generator.chunking import chunk_by_tokens
from .quiz_generator.pdf_reading import check_file_size, read_pdf
from .quiz_generator.quiz_generation import fix_quiz, generate_quiz

logger = logging.getLogger(__name__)
SESSION_WINDOW = timedelta(hours=5)
WEEKLY_WINDOW = timedelta(days=7)
DEFAULT_MAX_OUTPUT_TOKENS = 4096
MIN_OUTPUT_TOKENS = 16
FALLBACK_SCOPES = {AIUsageScope.CHAT, AIUsageScope.HINT}


class AIUsageAccessDenied(PermissionError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class EffectiveAILimits:
    credits_session: int | None
    credits_weekly: int | None


def _decimal(value) -> Decimal:
    return Decimal(str(value))


def available_models_for_account_level(account_level):
    return AIModel.objects.available_for_account_level(account_level).order_by("order", "provider", "model")


def available_models_for_user(user):
    return available_models_for_account_level(user.account_level)


def active_fallback_model_id(settings):
    model_id = settings.fallback_model_id
    if model_id is None:
        return None
    return model_id if AIModel.objects.filter(model=model_id, active=True, deleted_at__isnull=True).exists() else None


def get_limits(user, settings=None) -> EffectiveAILimits:
    settings = settings or AIUsageSettings.load()
    matrix = AIAccountLimit.objects.filter(
        account_type=user.account_type or AccountType.EMAIL,
        account_level=user.account_level or AccountLevel.BASIC,
    ).first()
    override = AIUserLimitOverride.objects.filter(user=user).first()
    return resolve_effective_limits(user, settings, matrix, override)


def resolve_effective_limits(user, settings, matrix, override) -> EffectiveAILimits:
    if (user.is_staff or user.is_superuser) and settings.staff_bypass_limits:
        return EffectiveAILimits(None, None)
    base = EffectiveAILimits(
        matrix.credits_session if matrix else 0,
        matrix.credits_weekly if matrix else 0,
    )
    if override is not None:
        return EffectiveAILimits(
            override.credits_session,
            override.credits_weekly,
        )
    return base


def quota_window_start(settings, now, window):
    window_start = now - window
    return max(window_start, settings.limits_reset_at) if settings.limits_reset_at is not None else window_start


def _quota_events(user, since):
    return AIUsageEvent.objects.filter(user=user, quota_exempt=False, created_at__gte=since)


def reset_at_from_events(events, window, limit, used, now):
    """Return the next time a rolling usage window gives credits back.

    Below the limit this is the first event expiry. Once the limit is reached,
    it is the first expiry that brings usage below the configured limit.
    """
    if limit is None or used <= 0:
        return None
    running = used
    for event in events:
        created_at = event["created_at"] if isinstance(event, dict) else event.created_at
        credits = event["credits"] if isinstance(event, dict) else event.credits
        if used < limit:
            return created_at + window
        running -= credits
        if running < limit:
            return created_at + window
    return now + window


def _reset_at(user, window, limit, used, now, *, since=None):
    events = _quota_events(user, since or now - window).order_by("created_at").only("created_at", "credits")
    return reset_at_from_events(events, window, limit, used, now)


def _window_summary(user, window, limit, used, now, *, include_reset=True, since=None):
    if limit is None:
        return {"used": used, "limit": None, "remaining": None, "resets_at": None}
    return {
        "used": used,
        "limit": limit,
        "remaining": limit - used,
        "resets_at": _reset_at(user, window, limit, used, now, since=since) if include_reset else None,
    }


def daily_event_totals(queryset):
    return list(
        queryset.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(credits=Sum("credits"), events=Count("id"))
        .order_by("day")
    )


def zero_fill_daily(rows, days, *, date_key):
    rows_by_day = {row["day"]: row for row in rows}
    today = timezone.localdate()
    return [
        {
            date_key: day,
            "credits": rows_by_day.get(day, {}).get("credits", Decimal("0")),
            "events": rows_by_day.get(day, {}).get("events", 0),
        }
        for offset in range(days - 1, -1, -1)
        for day in (today - timedelta(days=offset),)
    ]


def _latest_fallback_admission_at(user, *, since=None):
    grants = AIFallbackGrant.objects.filter(user=user)
    if since is not None:
        grants = grants.filter(issued_at__gte=since)
    return grants.order_by("-issued_at").values_list("issued_at", flat=True).first()


def get_usage_summary(user, days=30, settings=None):
    now = timezone.now()
    today = timezone.localdate(now)
    settings = settings or AIUsageSettings.load()
    limits = get_limits(user, settings)
    session_limit = limits.credits_session if settings.limits_enabled else None
    weekly_limit = limits.credits_weekly if settings.limits_enabled else None
    start_date = today - timedelta(days=days - 1)
    start_at = timezone.make_aware(datetime.combine(start_date, time.min), timezone.get_current_timezone())
    daily = zero_fill_daily(
        daily_event_totals(AIUsageEvent.objects.filter(user=user, created_at__gte=start_at)),
        days,
        date_key="date",
    )
    recent = AIUsageEvent.objects.filter(user=user, created_at__gte=start_at)
    by_model = list(recent.values("model").annotate(credits=Sum("credits"), events=Count("id")).order_by("-credits"))
    by_scope = list(recent.values("scope").annotate(credits=Sum("credits"), events=Count("id")).order_by("-credits"))
    weekly_start = quota_window_start(settings, now, WEEKLY_WINDOW)
    session_start = quota_window_start(settings, now, SESSION_WINDOW)
    quota_totals = AIUsageEvent.objects.filter(
        user=user,
        quota_exempt=False,
        created_at__gte=weekly_start,
    ).aggregate(
        weekly=Sum("credits"),
        session=Sum("credits", filter=Q(created_at__gte=session_start)),
    )
    session = _window_summary(
        user,
        SESSION_WINDOW,
        session_limit,
        quota_totals["session"] or Decimal("0"),
        now,
        since=session_start,
    )
    weekly = _window_summary(
        user,
        WEEKLY_WINDOW,
        weekly_limit,
        quota_totals["weekly"] or Decimal("0"),
        now,
        since=weekly_start,
    )
    exhausted = settings.limits_enabled and any(
        window["remaining"] is not None and window["remaining"] <= 0 for window in (session, weekly)
    )
    blocked_resets = [
        window["resets_at"]
        for window in (session, weekly)
        if window["remaining"] is not None and window["remaining"] <= 0 and window["resets_at"] is not None
    ]
    active_models = list(available_models_for_user(user).values_list("model", flat=True))
    fallback_model = active_fallback_model_id(settings)
    latest_fallback_at = (
        _latest_fallback_admission_at(user, since=settings.limits_reset_at)
        if settings.limits_enabled and fallback_model is not None
        else None
    )
    fallback_resets_at = (
        latest_fallback_at + timedelta(seconds=settings.fallback_throttle_seconds)
        if latest_fallback_at is not None
        else None
    )
    if fallback_resets_at is not None and fallback_resets_at <= now:
        fallback_resets_at = None
    return {
        "session": session,
        "weekly": weekly,
        "limits_enabled": settings.limits_enabled,
        "exhausted": exhausted,
        "blocked_until": max(blocked_resets) if exhausted and blocked_resets else None,
        "fallback_resets_at": fallback_resets_at,
        "active_models": active_models,
        "fallback_model": fallback_model,
        "daily": daily,
        "by_model": by_model,
        "by_scope": by_scope,
    }


@transaction.atomic
def _reserve_fallback_grant(user, model, throttle_seconds, *, since=None):
    """Atomically reserve one fallback generation for a user.

    Admission has to be recorded before generation begins. Usage events arrive
    asynchronously after a stream closes, so they cannot safely act as the
    throttle lock on their own.
    """
    type(user).objects.select_for_update().only("pk").get(pk=user.pk)
    now = timezone.now()
    latest_admission_at = _latest_fallback_admission_at(user, since=since)
    throttle_reset = (
        latest_admission_at + timedelta(seconds=throttle_seconds) if latest_admission_at is not None else None
    )
    if throttle_reset is not None and throttle_reset > now:
        return None, throttle_reset
    return AIFallbackGrant.objects.create(user=user, model_id=model), None


def _resolve_active_model(user, requested_model, settings, available_providers=None):
    active_models = {
        model.model: model
        for model in AIModel.objects.filter(active=True, deleted_at__isnull=True).order_by("order", "provider", "model")
        if available_providers is None or model.provider in available_providers
    }
    eligible_models = {
        model.model: model
        for model in available_models_for_user(user)
        if available_providers is None or model.provider in available_providers
    }
    preferred_models = (requested_model, settings.default_model_id)
    resolved_model = next(
        (model for model in preferred_models if model and model in eligible_models),
        next(iter(eligible_models), None),
    )
    return active_models, eligible_models, resolved_model


def _quota_exceeded_window(session, weekly):
    exceeded = None
    remaining_values = []
    for window, label in ((session, "session"), (weekly, "weekly")):
        remaining = window["remaining"]
        if remaining is not None:
            remaining_values.append(remaining)
            if remaining <= 0 and exceeded is None:
                exceeded = label
    return exceeded, remaining_values


def _output_token_budget(
    pricing,
    remaining_values,
    grace,
    *,
    estimated_input_tokens=None,
    maximum=DEFAULT_MAX_OUTPUT_TOKENS,
):
    if not remaining_values or pricing.output_weight <= 0:
        return maximum
    input_cost = (
        _decimal(estimated_input_tokens) * pricing.input_weight if estimated_input_tokens is not None else Decimal("0")
    )
    budget = max(Decimal("0"), min(remaining_values) + grace - input_cost)
    return max(MIN_OUTPUT_TOKENS, min(maximum, int(budget / pricing.output_weight)))


def _quota_decision(
    *,
    settings,
    allowed,
    would_block,
    exceeded_window,
    resets_at,
    usage,
    suggested_max_output_tokens,
    quota_tier,
    fallback_model,
    fallback_grant_id,
    fallback_resets_at,
    resolved_model,
    resolved_provider,
    active_models,
):
    return {
        "allowed": allowed,
        "would_block": would_block,
        "limits_enabled": settings.limits_enabled,
        "exceeded_window": exceeded_window,
        "resets_at": resets_at,
        "usage": usage,
        "suggested_max_output_tokens": suggested_max_output_tokens,
        "quota_tier": quota_tier,
        "fallback_model": fallback_model,
        "fallback_grant_id": fallback_grant_id,
        "fallback_resets_at": fallback_resets_at,
        "resolved_model": resolved_model,
        "resolved_provider": resolved_provider,
        "active_models": active_models,
    }


def check_quota(
    user,
    estimated_input_tokens=None,
    scope=None,
    requested_model=None,
    available_providers=None,
):
    if not user.is_active:
        raise AIUsageAccessDenied("account_disabled")
    try:
        ai_disabled = user.settings.ai_disabled
    except UserSettings.DoesNotExist:
        ai_disabled = False
    if ai_disabled:
        raise AIUsageAccessDenied("ai_disabled")

    now = timezone.now()
    settings = AIUsageSettings.load()
    limits = get_limits(user, settings)
    weekly_start = quota_window_start(settings, now, WEEKLY_WINDOW)
    session_start = quota_window_start(settings, now, SESSION_WINDOW)
    quota_events = AIUsageEvent.objects.filter(
        user=user,
        quota_exempt=False,
        created_at__gte=weekly_start,
    )
    totals = quota_events.aggregate(
        weekly=Sum("credits"),
        session=Sum("credits", filter=Q(created_at__gte=session_start)),
    )
    session = _window_summary(
        user,
        SESSION_WINDOW,
        limits.credits_session,
        totals["session"] or Decimal("0"),
        now,
        include_reset=False,
    )
    weekly = _window_summary(
        user,
        WEEKLY_WINDOW,
        limits.credits_weekly,
        totals["weekly"] or Decimal("0"),
        now,
        include_reset=False,
    )
    usage = {"session": session, "weekly": weekly}
    active_pricing, eligible_pricing, resolved_model = _resolve_active_model(
        user,
        requested_model,
        settings,
        available_providers,
    )
    active_models = list(eligible_pricing)
    pricing = active_pricing.get(resolved_model)
    quota_exceeded, remaining_values = _quota_exceeded_window(session, weekly)
    exceeded = quota_exceeded
    grace = settings.grace_buffer_credits
    estimated_input_cost = (
        _decimal(estimated_input_tokens) * pricing.input_weight
        if pricing is not None and estimated_input_tokens is not None
        else Decimal("0")
    )
    minimum_request_cost = (
        estimated_input_cost + pricing.output_weight * MIN_OUTPUT_TOKENS if pricing is not None else Decimal("0")
    )
    preblocked = bool(remaining_values) and pricing is not None and minimum_request_cost > min(remaining_values) + grace
    if preblocked and exceeded is None:
        exceeded = "input"
    if pricing is None and exceeded is None:
        exceeded = "model_unavailable"
    would_block = exceeded is not None
    allowed = pricing is not None and (not would_block or not settings.limits_enabled)
    quota_tier = "normal"
    fallback_model = None
    fallback_grant_id = None
    fallback_resets_at = None
    throttle_reset = None
    if (
        settings.limits_enabled
        and not allowed
        and settings.fallback_model_id is not None
        and scope in FALLBACK_SCOPES
        and quota_exceeded in {"session", "weekly"}
    ):
        quota_tier = "fallback"
        fallback_pricing = active_pricing.get(settings.fallback_model_id)
        provider_available = fallback_pricing is not None and (
            available_providers is None or fallback_pricing.provider in available_providers
        )
        fallback_model = settings.fallback_model_id if provider_available else None
        if fallback_model is not None:
            resolved_model = fallback_model
            pricing = active_pricing[fallback_model]
        if fallback_model is None:
            exceeded = "model_unavailable"
            resolved_model = None
        else:
            grant, throttle_reset = _reserve_fallback_grant(
                user,
                fallback_model,
                settings.fallback_throttle_seconds,
                since=settings.limits_reset_at,
            )
            if grant is None:
                exceeded = "fallback_throttle"
            else:
                fallback_grant_id = grant.id
                fallback_resets_at = grant.issued_at + timedelta(seconds=settings.fallback_throttle_seconds)
                allowed = True
    if not settings.limits_enabled:
        suggested = DEFAULT_MAX_OUTPUT_TOKENS
    elif quota_tier == "fallback":
        suggested = max(
            MIN_OUTPUT_TOKENS,
            min(DEFAULT_MAX_OUTPUT_TOKENS, settings.fallback_max_output_tokens),
        )
    else:
        suggested = (
            _output_token_budget(
                pricing,
                remaining_values,
                grace,
                estimated_input_tokens=estimated_input_tokens,
            )
            if pricing is not None
            else DEFAULT_MAX_OUTPUT_TOKENS
        )
    resets = []
    if quota_exceeded in {"session", "weekly"}:
        for key, window, limit, used, since in (
            ("session", SESSION_WINDOW, limits.credits_session, totals["session"] or Decimal("0"), session_start),
            ("weekly", WEEKLY_WINDOW, limits.credits_weekly, totals["weekly"] or Decimal("0"), weekly_start),
        ):
            if usage[key]["remaining"] is not None and usage[key]["remaining"] <= 0:
                usage[key]["resets_at"] = _reset_at(user, window, limit, used, now, since=since)
                if usage[key]["resets_at"] is not None:
                    resets.append(usage[key]["resets_at"])
    if exceeded == "input" and pricing is not None:
        projected_resets = []
        permanently_too_large = False
        for window, limit, used, since in (
            (SESSION_WINDOW, limits.credits_session, totals["session"] or Decimal("0"), session_start),
            (WEEKLY_WINDOW, limits.credits_weekly, totals["weekly"] or Decimal("0"), weekly_start),
        ):
            if limit is None or used + minimum_request_cost <= limit + grace:
                continue
            reset = _reset_at_for_debit(
                user,
                window,
                limit,
                used,
                minimum_request_cost,
                grace,
                now,
                since=since,
            )
            if reset is None:
                permanently_too_large = True
            else:
                projected_resets.append(reset)
        resets = [] if permanently_too_large else projected_resets
    if exceeded == "fallback_throttle" and throttle_reset is not None:
        resets = [throttle_reset]
    response_usage = usage
    if not settings.limits_enabled:
        response_usage = {
            "session": _window_summary(
                user,
                SESSION_WINDOW,
                None,
                totals["session"] or Decimal("0"),
                now,
                include_reset=False,
            ),
            "weekly": _window_summary(
                user,
                WEEKLY_WINDOW,
                None,
                totals["weekly"] or Decimal("0"),
                now,
                include_reset=False,
            ),
        }
    return _quota_decision(
        settings=settings,
        allowed=allowed,
        would_block=would_block,
        exceeded_window=exceeded,
        resets_at=max(resets) if settings.limits_enabled and resets else None,
        usage=response_usage,
        suggested_max_output_tokens=suggested,
        quota_tier=quota_tier,
        fallback_model=fallback_model,
        fallback_grant_id=fallback_grant_id,
        fallback_resets_at=fallback_resets_at,
        resolved_model=resolved_model,
        resolved_provider=pricing.provider if resolved_model is not None else None,
        active_models=active_models,
    )


def _reset_at_for_debit(user, window, limit, used, debit, grace, now, *, since=None):
    if limit is None or debit > limit + grace or used + debit <= limit + grace:
        return None
    running = used
    for event in _quota_events(user, since or now - window).order_by("created_at").only("created_at", "credits"):
        running -= event.credits
        if running + debit <= limit + grace:
            return event.created_at + window
    return None


@transaction.atomic
def reset_all_limits():
    settings = AIUsageSettings.objects.select_for_update().get(pk=1)
    settings.limits_reset_at = timezone.now()
    settings.save(update_fields=("limits_reset_at", "updated_at"))
    return settings.limits_reset_at


def get_pricing(model, *, require_active=False):
    pricing = AIModel.objects.filter(model=model).first()
    if pricing is None:
        raise ValueError(f"Unknown model {model}")
    if require_active and (not pricing.active or pricing.deleted_at is not None):
        raise ValueError(f"Model {model} is unavailable")
    return pricing


def _consume_fallback_grant(user, scope, model, fallback_grant_id):
    if scope not in FALLBACK_SCOPES or fallback_grant_id is None:
        return False
    grant = (
        AIFallbackGrant.objects.select_for_update()
        .filter(
            pk=fallback_grant_id,
            user=user,
            model_id=model,
            consumed_at__isnull=True,
        )
        .first()
    )
    if grant is None:
        return False
    grant.consumed_at = timezone.now()
    grant.save(update_fields=("consumed_at",))
    return True


def _message_id(message):
    explicit_id = message.get("id")
    if explicit_id:
        return str(explicit_id)[:100]
    content = message.get("parts") if message.get("parts") is not None else (message.get("content") or [])
    fingerprint = json.dumps(
        {"role": message.get("role") or "unknown", "content": content, "model": message.get("model") or ""},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"auto-{hashlib.sha256(fingerprint).hexdigest()}"


def _attach_conversation(*, user, conversation_id, quiz_id, scope, messages, metadata, model):
    if not conversation_id:
        return None
    try:
        with transaction.atomic():
            conversation = AIChatConversation.objects.select_for_update().filter(pk=conversation_id).first()
            if conversation is None:
                conversation = AIChatConversation.objects.create(
                    id=conversation_id, user=user, quiz_id=quiz_id, scope=scope
                )
            if conversation.user_id != user.id:
                logger.warning(
                    "Usage recorded without foreign conversation %s for user %s",
                    conversation_id,
                    user.pk,
                )
                return None
            if quiz_id and conversation.quiz_id and conversation.quiz_id != quiz_id:
                logger.warning(
                    "Usage recorded without mismatched conversation %s for quiz %s",
                    conversation_id,
                    quiz_id,
                )
                return None
            if quiz_id and conversation.quiz_id is None:
                conversation.quiz_id = quiz_id
            if messages:
                first_user = next((message for message in messages if message.get("role") == "user"), None)
                if not conversation.title and first_user:
                    content = first_user.get("parts", first_user.get("content", []))
                    conversation.title = _message_text(content).strip()[:200]
                message_mode = (metadata or {}).get("messages_mode")
                existing_messages = AIChatMessage.objects.filter(conversation=conversation)
                normalized_messages = [(_message_id(message), message) for message in messages]
                requested_model_ids = {message.get("model") for message in messages if message.get("model")}
                known_model_ids = set(
                    AIModel.objects.filter(model__in=requested_model_ids).values_list("model", flat=True)
                )
                if message_mode == "append":
                    existing_messages.filter(
                        message_id__in=[message_id for message_id, _ in normalized_messages]
                    ).delete()
                    max_order = existing_messages.aggregate(max_order=Max("order"))["max_order"]
                    start_order = 0 if max_order is None else max_order + 1
                else:
                    existing_messages.delete()
                    start_order = 0
                AIChatMessage.objects.bulk_create(
                    [
                        AIChatMessage(
                            conversation=conversation,
                            message_id=message_id,
                            role=message.get("role") or "unknown",
                            content=(
                                message.get("parts")
                                if message.get("parts") is not None
                                else (message.get("content") or [])
                            ),
                            model_id=(
                                message.get("model")
                                if message.get("model") in known_model_ids
                                else model.model
                                if message.get("role") == "assistant"
                                else None
                            ),
                            order=start_order + index,
                        )
                        for index, (message_id, message) in enumerate(normalized_messages)
                    ]
                )
            conversation.save()
            return conversation
    except IntegrityError as error:
        logger.warning("Usage recorded without conversation %s: %s", conversation_id, error)
        return None


def record_usage(
    *,
    user,
    scope,
    model,
    input_tokens=0,
    output_tokens=0,
    cache_read_tokens=0,
    cache_write_tokens=0,
    request_id,
    conversation_id=None,
    quiz_id=None,
    aborted=False,
    finish_reason="",
    error="",
    latency_ms=None,
    metadata=None,
    messages=None,
    fallback_grant_id=None,
):
    pricing = get_pricing(model)
    credits = (
        _decimal(input_tokens) * pricing.input_weight
        + _decimal(output_tokens) * pricing.output_weight
        + _decimal(cache_read_tokens) * pricing.cache_read_weight
        + _decimal(cache_write_tokens) * pricing.cache_write_weight
    )
    if quiz_id:
        try:
            quiz_id = get_readable_quiz(user, quiz_id).pk
        except QuizOperationError:
            logger.warning("Ignoring inaccessible quiz %s while recording AI usage for user %s", quiz_id, user.pk)
            quiz_id = None
    safe_metadata = {key: value for key, value in (metadata or {}).items() if key != "quota_tier"}
    with transaction.atomic():
        existing = AIUsageEvent.objects.filter(request_id=request_id).first()
        if existing is None:
            quota_exempt = _consume_fallback_grant(user, scope, model, fallback_grant_id)
            if quota_exempt:
                safe_metadata["quota_tier"] = "fallback"
            event, created = AIUsageEvent.objects.get_or_create(
                request_id=request_id,
                defaults={
                    "user": user,
                    "scope": scope,
                    "model": pricing,
                    "input_tokens": max(0, input_tokens),
                    "output_tokens": max(0, output_tokens),
                    "cache_read_tokens": max(0, cache_read_tokens),
                    "cache_write_tokens": max(0, cache_write_tokens),
                    "credits": credits,
                    "quiz_id": quiz_id,
                    "aborted": aborted,
                    "finish_reason": finish_reason,
                    "error": error,
                    "latency_ms": latency_ms,
                    "metadata": safe_metadata,
                    "quota_exempt": quota_exempt,
                },
            )
        else:
            event, created = existing, False

    if event.user_id != user.id:
        raise ValueError("Request ID already belongs to another user")
    conversation = None
    if event.conversation_id is None:
        conversation = _attach_conversation(
            user=user,
            conversation_id=conversation_id,
            quiz_id=quiz_id,
            scope=scope,
            messages=messages,
            metadata=metadata,
            model=pricing,
        )
    if conversation is not None:
        AIUsageEvent.objects.filter(pk=event.pk).update(conversation=conversation)
        event.conversation = conversation
    return event, created


@transaction.atomic
def soft_delete_model(model):
    settings = AIUsageSettings.objects.select_for_update().get(pk=1)
    model = AIModel.objects.select_for_update().get(pk=model.pk)
    if model.deleted_at is not None:
        return model
    if model.model in {settings.default_model_id, settings.fallback_model_id}:
        raise ValueError("Change the default or fallback model before deleting it.")
    UserSettings.objects.filter(default_ai_model=model).update(default_ai_model=None)
    model.active = False
    model.deleted_at = timezone.now()
    model.save(update_fields=("active", "deleted_at", "updated_at"))
    return model


def _message_text(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return " ".join(
        text
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
        for text in (part.get("text"),)
        if isinstance(text, str)
    )


def generate_json_quiz_from_pdf(*, user, pdf_file, question_count=10, difficulty="medium", request_id):

    # read PDF file and chunk it
    check_file_size(pdf_file)
    text = read_pdf(pdf_file)
    blocks = [b.strip() for b in text.replace("\r", "").split("\n\n") if b.strip()]
    chunks = chunk_by_tokens(blocks)
    full_content = "\n\n".join(c["text"] for c in chunks)

    # generate quiz
    generated_quiz, usage_info = generate_quiz(full_content, question_count, difficulty)

    quiz_dict = generated_quiz.model_dump()
    final_quiz = fix_quiz(quiz_dict)

    record_usage(
        user=user,
        scope=AIUsageScope.QUIZ_GENERATION,
        model=usage_info["model"],
        input_tokens=usage_info.get("input_tokens", 0),
        output_tokens=usage_info.get("output_tokens", 0),
        cached_tokens=usage_info.get("cached_tokens", 0),
        request_id=request_id,
        metadata={
            "question_count": question_count,
            "difficulty": difficulty,
        },
    )

    return final_quiz
