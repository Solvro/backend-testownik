from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import CharField, Count, F, Max, Min, Q, Sum, Value
from django.db.models.functions import Concat
from django.utils import timezone

from users.models import AccountLevel, AccountType, User

from .models import (
    AIAccountLimit,
    AIFallbackGrant,
    AIUsageDailyAggregate,
    AIUsageEvent,
    AIUsageSettings,
    AIUserLimitOverride,
)
from .services import (
    SESSION_WINDOW,
    WEEKLY_WINDOW,
    active_fallback_model_id,
    available_models_for_account_level,
    daily_event_totals,
    quota_window_start,
    reset_at_from_events,
    resolve_effective_limits,
    zero_fill_daily,
)


def _combine_grouped_rows(current_rows, aggregate_rows, key_fields):
    combined = {}
    for row in [*current_rows, *aggregate_rows]:
        key = tuple(row[field] for field in key_fields)
        target = combined.setdefault(
            key,
            {field: row[field] for field in key_fields} | {"credits": Decimal("0"), "events": 0},
        )
        target["credits"] += row.get("credits") or Decimal("0")
        target["events"] += row.get("events") or 0
    return sorted(combined.values(), key=lambda row: row["credits"], reverse=True)


def _usage_window(used, limit, resets_at):
    return {
        "used": used,
        "limit": limit,
        "remaining": None if limit is None else limit - used,
        "resets_at": None if limit is None else resets_at,
    }


def _usage_reset(events, window, limit, used, first_event_at, now, *, exhausted):
    if limit is None:
        return None
    if exhausted:
        return reset_at_from_events(events, window, limit, used, now)
    return first_event_at + window if first_event_at is not None else None


def get_admin_users(*, query="", overrides_only=False, limit=100):
    users = User.objects.annotate(
        searchable_full_name=Concat("first_name", Value(" "), "last_name", output_field=CharField())
    )
    if overrides_only:
        users = users.filter(ai_limit_override__isnull=False)
    if query:
        users = users.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(searchable_full_name__icontains=query)
            | Q(id__icontains=query)
        )
    selected_users = list(users.order_by("email")[:limit])
    user_ids = [user.id for user in selected_users]
    settings = AIUsageSettings.load()
    limits_disabled = not settings.limits_enabled
    limit_rows = {(row.account_type, row.account_level): row for row in AIAccountLimit.objects.all()}
    overrides = {row.user_id: row for row in AIUserLimitOverride.objects.filter(user_id__in=user_ids)}
    now = timezone.now()
    weekly_start = quota_window_start(settings, now, WEEKLY_WINDOW)
    session_start = quota_window_start(settings, now, SESSION_WINDOW)
    usage_stats = {
        row["user_id"]: row
        for row in AIUsageEvent.objects.filter(
            user_id__in=user_ids,
            quota_exempt=False,
            created_at__gte=weekly_start,
        )
        .values("user_id")
        .annotate(
            weekly_used=Sum("credits"),
            session_used=Sum("credits", filter=Q(created_at__gte=session_start)),
            weekly_first=Min("created_at"),
            session_first=Min("created_at", filter=Q(created_at__gte=session_start)),
        )
    }
    latest_grants_query = (
        AIFallbackGrant.objects.filter(user_id__in=user_ids, issued_at__gte=settings.limits_reset_at)
        if settings.limits_reset_at is not None
        else AIFallbackGrant.objects.filter(user_id__in=user_ids)
    )
    latest_grants = dict(
        latest_grants_query.values("user_id").annotate(latest=Max("issued_at")).values_list("user_id", "latest")
    )
    active_models_by_level = {
        level: list(available_models_for_account_level(level).values_list("model", flat=True))
        for level in AccountLevel.values
    }
    fallback_model = active_fallback_model_id(settings)

    effective_by_user = {
        user.id: resolve_effective_limits(
            user,
            settings,
            limit_rows.get(
                (
                    user.account_type or AccountType.EMAIL,
                    user.account_level or AccountLevel.BASIC,
                )
            ),
            overrides.get(user.id),
        )
        for user in selected_users
    }
    exhausted_user_ids = set()
    for user in selected_users:
        effective = effective_by_user[user.id]
        session_limit = None if limits_disabled else effective.credits_session
        weekly_limit = None if limits_disabled else effective.credits_weekly
        stats = usage_stats.get(user.id, {})
        session_used = stats.get("session_used") or Decimal("0")
        weekly_used = stats.get("weekly_used") or Decimal("0")
        if (session_limit is not None and session_used >= session_limit) or (
            weekly_limit is not None and weekly_used >= weekly_limit
        ):
            exhausted_user_ids.add(user.id)
    events_by_user = {}
    for event in (
        AIUsageEvent.objects.filter(
            user_id__in=exhausted_user_ids,
            quota_exempt=False,
            created_at__gte=weekly_start,
        )
        .order_by("user_id", "created_at")
        .values("user_id", "created_at", "credits")
    ):
        events_by_user.setdefault(event["user_id"], []).append(event)

    rows = []
    for user in selected_users:
        effective = effective_by_user[user.id]
        session_limit = None if limits_disabled else effective.credits_session
        weekly_limit = None if limits_disabled else effective.credits_weekly
        stats = usage_stats.get(user.id, {})
        user_events = events_by_user.get(user.id, [])
        session_events = [event for event in user_events if event["created_at"] >= session_start]
        session_used = stats.get("session_used") or Decimal("0")
        weekly_used = stats.get("weekly_used") or Decimal("0")
        session_exhausted = session_limit is not None and session_used >= session_limit
        weekly_exhausted = weekly_limit is not None and weekly_used >= weekly_limit
        session_reset = _usage_reset(
            session_events,
            SESSION_WINDOW,
            session_limit,
            session_used,
            stats.get("session_first"),
            now,
            exhausted=session_exhausted,
        )
        weekly_reset = _usage_reset(
            user_events,
            WEEKLY_WINDOW,
            weekly_limit,
            weekly_used,
            stats.get("weekly_first"),
            now,
            exhausted=weekly_exhausted,
        )
        exhausted = session_exhausted or weekly_exhausted
        blocked_resets = [
            reset
            for is_exhausted, reset in (
                (session_exhausted, session_reset),
                (weekly_exhausted, weekly_reset),
            )
            if is_exhausted and reset is not None
        ]
        latest_grant_at = latest_grants.get(user.id) if settings.limits_enabled and fallback_model is not None else None
        fallback_resets_at = (
            latest_grant_at + timedelta(seconds=settings.fallback_throttle_seconds)
            if latest_grant_at is not None
            else None
        )
        if fallback_resets_at is not None and fallback_resets_at <= now:
            fallback_resets_at = None
        active_models = active_models_by_level.get(
            user.account_level or AccountLevel.BASIC,
            active_models_by_level[AccountLevel.BASIC],
        )
        rows.append(
            {
                "id": user.id,
                "email": user.email,
                "name": user.get_full_name(),
                "account_type": user.account_type,
                "account_level": user.account_level,
                "has_override": user.id in overrides,
                "usage": {
                    "session": _usage_window(
                        session_used,
                        session_limit,
                        session_reset,
                    ),
                    "weekly": _usage_window(
                        weekly_used,
                        weekly_limit,
                        weekly_reset,
                    ),
                    "limits_enabled": settings.limits_enabled,
                    "exhausted": exhausted,
                    "blocked_until": max(blocked_resets) if exhausted and blocked_resets else None,
                    "fallback_resets_at": fallback_resets_at,
                    "active_models": active_models,
                    "fallback_model": fallback_model,
                    "daily": [],
                    "by_model": [],
                    "by_scope": [],
                },
            }
        )
    return rows


def get_admin_stats(*, days):
    now = timezone.now()
    today = timezone.localdate(now)
    start_date = today - timedelta(days=days - 1)
    start_at = timezone.make_aware(datetime.combine(start_date, time.min), timezone.get_current_timezone())
    events = AIUsageEvent.objects.filter(created_at__gte=start_at)
    aggregates = AIUsageDailyAggregate.objects.filter(date__gte=start_date)
    totals = events.aggregate(
        credits=Sum("credits"),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        cache_read_tokens=Sum("cache_read_tokens"),
        cache_write_tokens=Sum("cache_write_tokens"),
        events=Count("id"),
        aborted=Count("id", filter=Q(aborted=True)),
        errors=Count("id", filter=~Q(error="")),
    )
    aggregate_totals = aggregates.aggregate(
        credits=Sum("credits"),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        cache_read_tokens=Sum("cache_read_tokens"),
        cache_write_tokens=Sum("cache_write_tokens"),
        events=Sum("event_count"),
        aborted=Sum("aborted_count"),
        errors=Sum("error_count"),
    )
    for key in (
        "credits",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "events",
        "aborted",
        "errors",
    ):
        totals[key] = (totals[key] or 0) + (aggregate_totals[key] or 0)
    by_model = _combine_grouped_rows(
        list(
            events.values(
                "model",
                label=F("model__label"),
                provider=F("model__provider"),
            )
            .annotate(credits=Sum("credits"), events=Count("id"))
            .order_by("-credits")
        ),
        list(
            aggregates.values(
                "model",
                label=F("model__label"),
                provider=F("model__provider"),
            ).annotate(credits=Sum("credits"), events=Sum("event_count"))
        ),
        ("model", "label", "provider"),
    )
    by_scope = _combine_grouped_rows(
        list(events.values("scope").annotate(credits=Sum("credits"), events=Count("id")).order_by("-credits")),
        list(aggregates.values("scope").annotate(credits=Sum("credits"), events=Sum("event_count"))),
        ("scope",),
    )
    daily_rows = _combine_grouped_rows(
        daily_event_totals(events),
        list(
            aggregates.values(day=F("date")).values("day").annotate(credits=Sum("credits"), events=Sum("event_count"))
        ),
        ("day",),
    )
    top_users = _combine_grouped_rows(
        list(events.values("user_id", "user__email").annotate(credits=Sum("credits"), events=Count("id"))),
        list(aggregates.values("user_id", "user__email").annotate(credits=Sum("credits"), events=Sum("event_count"))),
        ("user_id", "user__email"),
    )[:20]
    return {
        "totals": totals,
        "by_model": by_model,
        "by_scope": by_scope,
        "top_users": top_users,
        "daily": zero_fill_daily(daily_rows, days, date_key="day"),
        "limits_enabled": AIUsageSettings.load().limits_enabled,
    }
