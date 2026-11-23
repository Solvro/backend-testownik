from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from users.account_levels import add_calendar_months, get_account_level_state, grant_account_level
from users.models import AccountLevel, AccountLevelGrant, AccountLevelGrantSource, AccountType, User


class AccountLevelStateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(email="levels@example.com", account_level=AccountLevel.BASIC)
        self.now = timezone.now()

    def _grant(self, level, *, starts_at=None, expires_at=None):
        return AccountLevelGrant.objects.create(
            user=self.user,
            level=level,
            source=AccountLevelGrantSource.ADMIN,
            starts_at=starts_at or self.now,
            expires_at=expires_at,
        )

    def test_expiration_is_exclusive_and_reports_next_level(self):
        expires_at = self.now + timedelta(days=30)
        self._grant(AccountLevel.SILVER, expires_at=expires_at)

        before_expiration = get_account_level_state(self.user, at=expires_at - timedelta(microseconds=1))
        at_expiration = get_account_level_state(self.user, at=expires_at)

        self.assertEqual(before_expiration.effective_level, AccountLevel.SILVER)
        self.assertEqual(before_expiration.expires_at, expires_at)
        self.assertEqual(before_expiration.next_level, AccountLevel.BASIC)
        self.assertEqual(at_expiration.effective_level, AccountLevel.BASIC)

    def test_overlapping_grants_determine_level_and_next_expiration(self):
        silver_expiry = self.now + timedelta(days=30)
        gold_expiry = self.now + timedelta(days=10)
        self._grant(AccountLevel.SILVER, expires_at=silver_expiry)
        self._grant(AccountLevel.GOLD, expires_at=gold_expiry)

        current = get_account_level_state(self.user, at=self.now + timedelta(days=1))
        after_gold = get_account_level_state(self.user, at=gold_expiry)

        self.assertEqual(
            (current.effective_level, current.expires_at, current.next_level),
            (
                AccountLevel.GOLD,
                gold_expiry,
                AccountLevel.SILVER,
            ),
        )
        self.assertEqual(
            (after_gold.effective_level, after_gold.expires_at, after_gold.next_level),
            (
                AccountLevel.SILVER,
                silver_expiry,
                AccountLevel.BASIC,
            ),
        )

    def test_contiguous_same_level_grant_extends_the_current_level(self):
        first_expiry = self.now + timedelta(days=10)
        final_expiry = self.now + timedelta(days=30)
        self._grant(AccountLevel.GOLD, expires_at=first_expiry)
        self._grant(
            AccountLevel.GOLD,
            starts_at=first_expiry,
            expires_at=final_expiry,
        )

        state = get_account_level_state(self.user, at=self.now)

        self.assertEqual(state.effective_level, AccountLevel.GOLD)
        self.assertEqual(state.expires_at, final_expiry)
        self.assertEqual(state.next_level, AccountLevel.BASIC)

    def test_gap_between_same_level_grants_is_reported_as_a_level_change(self):
        first_expiry = self.now + timedelta(days=10)
        self._grant(AccountLevel.SILVER, expires_at=first_expiry)
        self._grant(
            AccountLevel.SILVER,
            starts_at=first_expiry + timedelta(days=5),
            expires_at=self.now + timedelta(days=30),
        )

        state = get_account_level_state(self.user, at=self.now)

        self.assertEqual(state.effective_level, AccountLevel.SILVER)
        self.assertEqual(state.expires_at, first_expiry)
        self.assertEqual(state.next_level, AccountLevel.BASIC)

    def test_future_grant_does_not_make_the_current_level_appear_to_expire(self):
        starts_at = self.now + timedelta(days=5)
        expires_at = self.now + timedelta(days=20)
        self._grant(AccountLevel.SILVER, starts_at=starts_at, expires_at=expires_at)

        state = get_account_level_state(self.user, at=self.now)

        self.assertEqual(state.effective_level, AccountLevel.BASIC)
        self.assertIsNone(state.expires_at)
        self.assertIsNone(state.next_level)

    def test_future_higher_grant_does_not_change_current_level_expiry(self):
        silver_expiry = self.now + timedelta(days=20)
        gold_start = self.now + timedelta(days=5)
        gold_expiry = self.now + timedelta(days=10)
        self._grant(AccountLevel.SILVER, expires_at=silver_expiry)
        self._grant(AccountLevel.GOLD, starts_at=gold_start, expires_at=gold_expiry)

        state = get_account_level_state(self.user, at=self.now)

        self.assertEqual(state.effective_level, AccountLevel.SILVER)
        self.assertEqual(state.expires_at, silver_expiry)
        self.assertEqual(state.next_level, AccountLevel.BASIC)

    def test_future_grant_starting_at_expiry_is_active_at_the_transition(self):
        first_expiry = self.now + timedelta(days=10)
        final_expiry = self.now + timedelta(days=30)
        self._grant(AccountLevel.GOLD, expires_at=first_expiry)
        self._grant(AccountLevel.SILVER, starts_at=first_expiry, expires_at=final_expiry)

        state = get_account_level_state(self.user, at=self.now)

        self.assertEqual(state.effective_level, AccountLevel.GOLD)
        self.assertEqual(state.expires_at, first_expiry)
        self.assertEqual(state.next_level, AccountLevel.SILVER)

    def test_current_level_continues_through_a_chained_future_grant(self):
        first_expiry = self.now + timedelta(days=10)
        final_expiry = self.now + timedelta(days=30)
        self._grant(AccountLevel.GOLD, expires_at=first_expiry)
        self._grant(
            AccountLevel.GOLD,
            starts_at=self.now + timedelta(days=5),
            expires_at=final_expiry,
        )

        state = get_account_level_state(self.user, at=self.now)

        self.assertEqual(state.effective_level, AccountLevel.GOLD)
        self.assertEqual(state.expires_at, final_expiry)
        self.assertEqual(state.next_level, AccountLevel.BASIC)

    def test_permanent_higher_level_has_no_expiry(self):
        self.user.account_level = AccountLevel.GOLD
        self.user.save(update_fields=["account_level"])
        self._grant(AccountLevel.SILVER, expires_at=self.now + timedelta(days=1))

        state = get_account_level_state(self.user, at=self.now)

        self.assertEqual(state.effective_level, AccountLevel.GOLD)
        self.assertIsNone(state.expires_at)
        self.assertIsNone(state.next_level)

    def test_indefinite_grant_has_no_expiry(self):
        grant = grant_account_level(
            self.user,
            AccountLevel.SILVER,
            AccountLevelGrantSource.REWARD,
            indefinite=True,
        )

        state = get_account_level_state(self.user, at=grant.starts_at)

        self.assertEqual(state.effective_level, AccountLevel.SILVER)
        self.assertIsNone(state.expires_at)

    def test_naive_state_time_is_rejected(self):
        with self.assertRaises(ValidationError):
            get_account_level_state(self.user, at=datetime(2026, 1, 1))


class AccountLevelGrantServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(email="grant-service@example.com")

    def test_month_duration_uses_calendar_end_of_month(self):
        start = datetime(2026, 1, 31, 12, tzinfo=ZoneInfo("Europe/Warsaw"))

        expiry = add_calendar_months(start, 1)

        self.assertEqual(
            expiry.astimezone(ZoneInfo("Europe/Warsaw")), datetime(2026, 2, 28, 12, tzinfo=ZoneInfo("Europe/Warsaw"))
        )

    def test_grant_for_month_uses_supplied_start(self):
        start = datetime(2026, 1, 31, 11, tzinfo=UTC)

        grant = grant_account_level(
            self.user,
            AccountLevel.SILVER,
            AccountLevelGrantSource.ADMIN,
            duration_months=1,
            starts_at=start,
        )

        self.assertEqual(grant.starts_at, start)
        self.assertEqual(grant.expires_at, add_calendar_months(start, 1))

    def test_exactly_one_expiry_mode_is_required(self):
        with self.assertRaises(ValidationError):
            grant_account_level(self.user, AccountLevel.SILVER, AccountLevelGrantSource.ADMIN)
        with self.assertRaises(ValidationError):
            grant_account_level(
                self.user,
                AccountLevel.SILVER,
                AccountLevelGrantSource.ADMIN,
                indefinite=True,
                duration_days=1,
            )

    def test_indefinite_must_be_boolean(self):
        with self.assertRaises(ValidationError) as error:
            grant_account_level(
                self.user,
                AccountLevel.SILVER,
                AccountLevelGrantSource.ADMIN,
                indefinite="yes",
            )

        self.assertIn("indefinite", error.exception.message_dict)

    def test_naive_start_and_expiry_are_rejected(self):
        with self.assertRaises(ValidationError):
            grant_account_level(
                self.user,
                AccountLevel.SILVER,
                AccountLevelGrantSource.ADMIN,
                duration_days=1,
                starts_at=datetime(2026, 1, 1),
            )
        with self.assertRaises(ValidationError):
            grant_account_level(
                self.user,
                AccountLevel.SILVER,
                AccountLevelGrantSource.ADMIN,
                expires_at=datetime(2026, 1, 2),
            )

    def test_expired_deadline_and_non_integer_durations_are_rejected(self):
        with self.assertRaises(ValidationError):
            grant_account_level(
                self.user,
                AccountLevel.SILVER,
                AccountLevelGrantSource.ADMIN,
                expires_at=timezone.now() - timedelta(seconds=1),
            )
        with self.assertRaises(ValidationError):
            grant_account_level(
                self.user,
                AccountLevel.SILVER,
                AccountLevelGrantSource.ADMIN,
                duration_days=1.5,
            )

    def test_same_source_reference_is_idempotent_for_same_user_and_rejected_for_another(self):
        grant = grant_account_level(
            self.user,
            AccountLevel.SILVER,
            AccountLevelGrantSource.REWARD,
            indefinite=True,
            source_ref="reward-1",
        )
        repeated = grant_account_level(
            self.user,
            AccountLevel.SILVER,
            AccountLevelGrantSource.REWARD,
            indefinite=True,
            source_ref="reward-1",
        )
        other_user = User.objects.create(email="other-grant-service@example.com")

        self.assertEqual(repeated.pk, grant.pk)
        self.assertEqual(AccountLevelGrant.objects.count(), 1)
        with self.assertRaises(ValidationError):
            grant_account_level(
                other_user,
                AccountLevel.SILVER,
                AccountLevelGrantSource.REWARD,
                indefinite=True,
                source_ref="reward-1",
            )
        with self.assertRaises(ValidationError):
            grant_account_level(
                self.user,
                AccountLevel.GOLD,
                AccountLevelGrantSource.REWARD,
                indefinite=True,
                source_ref="reward-1",
            )

    def test_same_source_reference_rejects_different_expiry_details(self):
        start = timezone.now()
        grant = grant_account_level(
            self.user,
            AccountLevel.SILVER,
            AccountLevelGrantSource.REWARD,
            duration_days=30,
            starts_at=start,
            source_ref="reward-expiry",
        )

        with self.assertRaises(ValidationError) as error:
            grant_account_level(
                self.user,
                AccountLevel.SILVER,
                AccountLevelGrantSource.REWARD,
                duration_days=31,
                starts_at=start,
                source_ref="reward-expiry",
            )

        self.assertIn("source_ref", error.exception.message_dict)
        self.assertEqual(AccountLevelGrant.objects.count(), 1)
        self.assertEqual(grant.expires_at - grant.starts_at, timedelta(days=30))

    def test_duration_retry_uses_original_start_and_still_matches_after_expiry(self):
        start = timezone.now() - timedelta(days=3)
        grant = grant_account_level(
            self.user,
            AccountLevel.SILVER,
            AccountLevelGrantSource.REWARD,
            duration_days=1,
            starts_at=start,
            source_ref="expired-reward",
        )

        repeated = grant_account_level(
            self.user,
            AccountLevel.SILVER,
            AccountLevelGrantSource.REWARD,
            duration_days=1,
            source_ref="expired-reward",
        )

        self.assertEqual(repeated.pk, grant.pk)
        self.assertEqual(AccountLevelGrant.objects.count(), 1)

    def test_same_source_reference_rejects_different_explicit_expiry(self):
        start = timezone.now()
        expires_at = start + timedelta(days=30)
        grant_account_level(
            self.user,
            AccountLevel.SILVER,
            AccountLevelGrantSource.REWARD,
            expires_at=expires_at,
            starts_at=start,
            source_ref="reward-deadline",
        )

        with self.assertRaises(ValidationError) as error:
            grant_account_level(
                self.user,
                AccountLevel.SILVER,
                AccountLevelGrantSource.REWARD,
                expires_at=expires_at + timedelta(days=1),
                starts_at=start,
                source_ref="reward-deadline",
            )

        self.assertIn("source_ref", error.exception.message_dict)
        self.assertEqual(AccountLevelGrant.objects.count(), 1)

    def test_guest_and_basic_grants_are_rejected(self):
        guest = User.objects.create(account_type=AccountType.GUEST)
        with self.assertRaises(ValidationError):
            grant_account_level(guest, AccountLevel.SILVER, AccountLevelGrantSource.ADMIN, indefinite=True)
        with self.assertRaises(ValidationError):
            grant_account_level(self.user, AccountLevel.BASIC, AccountLevelGrantSource.ADMIN, indefinite=True)
