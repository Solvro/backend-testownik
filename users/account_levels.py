import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Case, CharField, Exists, IntegerField, OuterRef, Prefetch, Q, QuerySet, Value, When
from django.utils import timezone

from users.models import AccountLevel, AccountLevelGrant, AccountLevelGrantSource, AccountType, User

LEVEL_ORDER: dict[AccountLevel, int] = {
    AccountLevel.BASIC: 0,
    AccountLevel.SILVER: 1,
    AccountLevel.GOLD: 2,
}

MAX_DURATION_MONTHS = 120
MAX_DURATION_DAYS = 3650


@dataclass(frozen=True)
class AccountLevelState:
    effective_level: AccountLevel
    permanent_level: AccountLevel
    expires_at: datetime | None
    next_level: AccountLevel | None


def add_calendar_months(dt: datetime, months: int) -> datetime:
    if timezone.is_naive(dt):
        raise ValidationError({"starts_at": "starts_at must include a timezone."})
    if isinstance(months, bool) or not isinstance(months, int) or months <= 0:
        raise ValidationError({"duration_months": "Duration in months must be a positive integer."})

    local_dt = dt.astimezone(ZoneInfo(settings.TIME_ZONE))
    total_months = local_dt.month - 1 + months
    target_year = local_dt.year + total_months // 12
    target_month = total_months % 12 + 1
    target_day = min(local_dt.day, calendar.monthrange(target_year, target_month)[1])

    target_local = local_dt.replace(year=target_year, month=target_month, day=target_day)
    return target_local.astimezone(UTC)


def _highest_level_at(permanent_level: AccountLevel, grants: list[AccountLevelGrant], moment: datetime) -> AccountLevel:
    best = permanent_level
    for grant in grants:
        if grant.starts_at <= moment and (grant.expires_at is None or grant.expires_at > moment):
            grant_level = AccountLevel(grant.level)
            if LEVEL_ORDER[grant_level] > LEVEL_ORDER[best]:
                best = grant_level
    return best


def get_account_level_state(user: User, *, at: datetime | None = None) -> AccountLevelState:
    at = at if at is not None else timezone.now()
    if timezone.is_naive(at):
        raise ValidationError({"at": "at must include a timezone."})

    permanent_level = AccountLevel(user.account_level)
    if user._state.adding:
        return AccountLevelState(permanent_level, permanent_level, None, None)

    grants = list(user.account_level_grants.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=at)))
    effective_level = _highest_level_at(permanent_level, grants, at)
    expiry_times = {grant.expires_at for grant in grants if grant.expires_at is not None}

    for expires_at in sorted(expiry_times):
        next_level = _highest_level_at(permanent_level, grants, expires_at)
        if LEVEL_ORDER[next_level] < LEVEL_ORDER[effective_level]:
            return AccountLevelState(effective_level, permanent_level, expires_at, next_level)

    return AccountLevelState(effective_level, permanent_level, None, None)


def annotate_effective_account_level(
    queryset: QuerySet[User],
    *,
    at: datetime | None = None,
) -> QuerySet[User]:
    at = at if at is not None else timezone.now()
    if timezone.is_naive(at):
        raise ValidationError({"at": "at must include a timezone."})

    active_window = Q(starts_at__lte=at) & (Q(expires_at__isnull=True) | Q(expires_at__gt=at))
    has_active_gold = Exists(
        AccountLevelGrant.objects.filter(active_window, user_id=OuterRef("pk"), level=AccountLevel.GOLD)
    )
    has_active_silver = Exists(
        AccountLevelGrant.objects.filter(active_window, user_id=OuterRef("pk"), level=AccountLevel.SILVER)
    )

    return queryset.annotate(
        _has_active_gold=has_active_gold,
        _has_active_silver=has_active_silver,
    ).annotate(
        _effective_account_level=Case(
            When(Q(account_level=AccountLevel.GOLD) | Q(_has_active_gold=True), then=Value(AccountLevel.GOLD)),
            When(Q(account_level=AccountLevel.SILVER) | Q(_has_active_silver=True), then=Value(AccountLevel.SILVER)),
            default=Value(AccountLevel.BASIC),
            output_field=CharField(),
        ),
        _effective_account_level_rank=Case(
            When(
                Q(account_level=AccountLevel.GOLD) | Q(_has_active_gold=True),
                then=Value(LEVEL_ORDER[AccountLevel.GOLD]),
            ),
            When(
                Q(account_level=AccountLevel.SILVER) | Q(_has_active_silver=True),
                then=Value(LEVEL_ORDER[AccountLevel.SILVER]),
            ),
            default=Value(LEVEL_ORDER[AccountLevel.BASIC]),
            output_field=IntegerField(),
        ),
    )


def active_grants_prefetch(relation: str = "", *, at: datetime | None = None) -> Prefetch:
    at = at if at is not None else timezone.now()
    if timezone.is_naive(at):
        raise ValidationError({"at": "at must include a timezone."})

    lookup = f"{relation}__account_level_grants" if relation else "account_level_grants"
    active_qs = AccountLevelGrant.objects.filter(starts_at__lte=at).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=at)
    )
    return Prefetch(lookup, queryset=active_qs, to_attr="_active_account_level_grants")


def get_effective_account_level(user: User, *, at: datetime | None = None) -> AccountLevel:
    if at is None:
        annotated = getattr(user, "_effective_account_level", None)
        if annotated is not None:
            return AccountLevel(annotated)
        prefetched = getattr(user, "_active_account_level_grants", None)
        if prefetched is not None:
            best = AccountLevel(user.account_level)
            for grant in prefetched:
                grant_level = AccountLevel(grant.level)
                if LEVEL_ORDER[grant_level] > LEVEL_ORDER[best]:
                    best = grant_level
            return best
    return get_account_level_state(user, at=at).effective_level


def _calculate_expiry(
    *,
    starts_at: datetime,
    indefinite: bool,
    duration_months: int | None,
    duration_days: int | None,
    expires_at: datetime | None,
) -> datetime | None:
    if not isinstance(indefinite, bool):
        raise ValidationError({"indefinite": "indefinite must be a boolean."})

    expiry_modes = (indefinite, duration_months is not None, duration_days is not None, expires_at is not None)
    if sum(expiry_modes) != 1:
        raise ValidationError(
            "Specify exactly one expiry mode: indefinite, duration_months, duration_days, or expires_at."
        )

    if indefinite:
        return None

    if duration_months is not None:
        if (
            isinstance(duration_months, bool)
            or not isinstance(duration_months, int)
            or not 1 <= duration_months <= MAX_DURATION_MONTHS
        ):
            raise ValidationError({"duration_months": f"duration_months must be between 1 and {MAX_DURATION_MONTHS}."})
        calculated_expiry = add_calendar_months(starts_at, duration_months)
    elif duration_days is not None:
        if (
            isinstance(duration_days, bool)
            or not isinstance(duration_days, int)
            or not 1 <= duration_days <= MAX_DURATION_DAYS
        ):
            raise ValidationError({"duration_days": f"duration_days must be between 1 and {MAX_DURATION_DAYS}."})
        calculated_expiry = starts_at + timedelta(days=duration_days)
    elif expires_at is not None:
        if timezone.is_naive(expires_at):
            raise ValidationError({"expires_at": "expires_at must include a timezone."})
        calculated_expiry = expires_at.astimezone(UTC)
    else:
        return None

    if calculated_expiry <= starts_at:
        raise ValidationError({"expires_at": "expires_at must be after starts_at."})
    return calculated_expiry


def _get_existing_grant(
    user: User,
    level: AccountLevel,
    source: AccountLevelGrantSource,
    source_ref: str | None,
) -> AccountLevelGrant | None:
    if source_ref is None:
        return None

    existing = AccountLevelGrant.objects.filter(source=source, source_ref=source_ref).first()
    if existing is not None:
        if existing.user_id != user.id:
            raise ValidationError({"source_ref": "This source_ref is already used for another user."})
        if existing.level != level:
            raise ValidationError({"source_ref": "This source_ref is already used with a different level."})
    return existing


def grant_account_level(
    user: User,
    level: str | AccountLevel,
    source: str | AccountLevelGrantSource,
    *,
    indefinite: bool = False,
    duration_months: int | None = None,
    duration_days: int | None = None,
    expires_at: datetime | None = None,
    starts_at: datetime | None = None,
    created_by: User | None = None,
    reason: str = "",
    source_ref: str | None = None,
) -> AccountLevelGrant:
    """Grant Silver or Gold indefinitely, for a duration, or until a specific datetime."""
    if user.account_type == AccountType.GUEST:
        raise ValidationError({"user": "Guest accounts cannot receive account level grants."})

    try:
        grant_level = AccountLevel(level)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"level": "Only Silver and Gold levels can be granted."}) from exc
    if grant_level not in (AccountLevel.SILVER, AccountLevel.GOLD):
        raise ValidationError({"level": "Only Silver and Gold levels can be granted."})

    try:
        grant_source = AccountLevelGrantSource(source)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"source": "Invalid grant source."}) from exc

    effective_start = starts_at if starts_at is not None else timezone.now()
    if timezone.is_naive(effective_start):
        raise ValidationError({"starts_at": "starts_at must include a timezone."})
    effective_start = effective_start.astimezone(UTC)
    computed_expiry = _calculate_expiry(
        starts_at=effective_start,
        indefinite=indefinite,
        duration_months=duration_months,
        duration_days=duration_days,
        expires_at=expires_at,
    )

    normalized_ref = (source_ref or "").strip() or None
    existing = _get_existing_grant(user, grant_level, grant_source, normalized_ref)
    if existing is not None:
        return existing

    try:
        with transaction.atomic():
            return AccountLevelGrant.objects.create(
                user=user,
                level=grant_level,
                source=grant_source,
                source_ref=normalized_ref,
                reason=reason.strip(),
                starts_at=effective_start,
                expires_at=computed_expiry,
                created_by=created_by,
            )
    except IntegrityError:
        existing = _get_existing_grant(user, grant_level, grant_source, normalized_ref)
        if existing is not None:
            return existing
        raise
