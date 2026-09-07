from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from ai.models import (
    AIAccountLimit,
    AIChatConversation,
    AIChatMessage,
    AIFallbackGrant,
    AIModel,
    AIUsageDailyAggregate,
    AIUsageEvent,
    AIUsageSettings,
    AIUserLimitOverride,
)
from ai.services import (
    SESSION_WINDOW,
    AIUsageAccessDenied,
    _reset_at,
    check_quota,
    get_limits,
    get_usage_summary,
    record_usage,
    reset_all_limits,
)
from quizzes.models import Quiz
from users.models import AccountLevel, AccountType, User, UserSettings


class AIUsageServicesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="usage@example.com", account_type=AccountType.EMAIL, account_level=AccountLevel.BASIC
        )
        self.settings = AIUsageSettings.load()

    def test_override_replaces_matrix_and_can_disable_one_window(self):
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 100, "credits_weekly": 500},
        )
        AIUserLimitOverride.objects.create(user=self.user, credits_session=None, credits_weekly=900)
        limits = get_limits(self.user)
        self.assertIsNone(limits.credits_session)
        self.assertEqual(limits.credits_weekly, 900)

    def test_null_override_disables_both_windows(self):
        AIUserLimitOverride.objects.create(user=self.user)
        limits = get_limits(self.user)
        self.assertIsNone(limits.credits_session)
        self.assertIsNone(limits.credits_weekly)

    def test_global_reset_starts_new_quota_windows_without_deleting_history(self):
        AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model_id="gpt-5.6-terra",
            credits=123,
            request_id="before-global-reset",
        )

        reset_at = reset_all_limits()
        summary = get_usage_summary(self.user, days=7)

        self.assertEqual(summary["session"]["used"], 0)
        self.assertEqual(summary["weekly"]["used"], 0)
        self.assertEqual(sum(row["credits"] for row in summary["daily"]), 123)
        self.assertTrue(AIUsageEvent.objects.filter(request_id="before-global-reset").exists())
        self.assertEqual(AIUsageSettings.load().limits_reset_at, reset_at)

    def test_global_reset_clears_existing_fallback_cooldowns(self):
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 0, "credits_weekly": 0},
        )
        self.settings.limits_enabled = True
        self.settings.fallback_throttle_seconds = 60
        self.settings.save(update_fields=("limits_enabled", "fallback_throttle_seconds"))

        first = check_quota(self.user, scope="hint")
        reset_all_limits()
        second = check_quota(self.user, scope="hint")

        self.assertTrue(first["allowed"])
        self.assertTrue(second["allowed"])
        self.assertNotEqual(first["fallback_grant_id"], second["fallback_grant_id"])

    def test_quota_rejects_user_who_disabled_ai(self):
        UserSettings.objects.create(user=self.user, ai_disabled=True)

        with self.assertRaisesMessage(AIUsageAccessDenied, "ai_disabled"):
            check_quota(self.user)

    def test_quota_rejects_banned_user(self):
        self.user.is_banned = True
        self.user.save(update_fields=("is_banned",))

        with self.assertRaisesMessage(AIUsageAccessDenied, "account_disabled"):
            check_quota(self.user)

    def test_pricing_and_idempotent_request_id(self):
        AIModel.objects.update_or_create(
            model="test-model",
            defaults={
                "label": "Test model",
                "provider": "openai",
                "input_weight": 1,
                "output_weight": 3,
                "cache_read_weight": Decimal("0.25"),
            },
        )
        event, created = record_usage(
            user=self.user,
            scope="chat",
            model="test-model",
            input_tokens=10,
            output_tokens=5,
            cache_read_tokens=4,
            request_id="same-request",
        )
        duplicate, duplicate_created = record_usage(
            user=self.user, scope="chat", model="test-model", input_tokens=999, request_id="same-request"
        )
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(event.pk, duplicate.pk)
        self.assertEqual(event.credits, Decimal("26"))

    def test_duplicate_report_can_repair_conversation_history(self):
        conversation_id = "52322d0a-e5e6-4d53-a482-3f5e0ea70626"
        payload = {
            "user": self.user,
            "scope": "chat",
            "model": "gpt-5.6-terra",
            "input_tokens": 1,
            "request_id": "repair-history",
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": "Repair me"}],
        }
        with patch("ai.services._attach_conversation", return_value=None):
            first, created = record_usage(**payload)

        duplicate, duplicate_created = record_usage(**payload)

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(first.pk, duplicate.pk)
        duplicate.refresh_from_db()
        self.assertEqual(str(duplicate.conversation_id), conversation_id)
        self.assertEqual(duplicate.conversation.messages.count(), 1)

    def test_request_id_collision_cannot_cross_user_ownership(self):
        other_user = User.objects.create_user(email="other-usage@example.com")
        event, _ = record_usage(
            user=self.user,
            scope="chat",
            model="gpt-5.6-terra",
            request_id="cross-user-collision",
        )

        with self.assertRaisesMessage(ValueError, "another user"):
            record_usage(
                user=other_user,
                scope="chat",
                model="gpt-5.6-terra",
                request_id="cross-user-collision",
                conversation_id="ed719cc7-3b83-46ef-89b5-89c23240594e",
            )

        event.refresh_from_db()
        self.assertIsNone(event.conversation_id)

    def test_duplicate_report_cannot_move_existing_conversation(self):
        first_conversation_id = "cd1ba17c-87df-4bfa-8011-ad0275bb9f2c"
        second_conversation_id = "7102a23e-f251-4972-9e2c-4bff97274b76"
        event, _ = record_usage(
            user=self.user,
            scope="chat",
            model="gpt-5.6-terra",
            request_id="immutable-conversation",
            conversation_id=first_conversation_id,
        )

        duplicate, created = record_usage(
            user=self.user,
            scope="chat",
            model="gpt-5.6-terra",
            request_id="immutable-conversation",
            conversation_id=second_conversation_id,
        )

        self.assertFalse(created)
        duplicate.refresh_from_db()
        self.assertEqual(duplicate.pk, event.pk)
        self.assertEqual(str(duplicate.conversation_id), first_conversation_id)
        self.assertFalse(AIChatConversation.objects.filter(pk=second_conversation_id).exists())

    def test_unknown_model_is_rejected(self):
        with self.assertRaisesMessage(ValueError, "Unknown model provider-model-added-today"):
            record_usage(
                user=self.user,
                scope="chat",
                model="provider-model-added-today",
                input_tokens=10,
                output_tokens=5,
                request_id="unknown-model",
            )

    def test_client_metadata_cannot_exempt_usage(self):
        event, _ = record_usage(
            user=self.user,
            scope="chat",
            model="gpt-5.6-terra",
            input_tokens=10,
            request_id="forged-fallback",
            metadata={"quota_tier": "fallback"},
        )

        self.assertFalse(event.quota_exempt)
        self.assertNotIn("quota_tier", event.metadata)

    def test_suggested_output_tokens_are_weighted(self):
        AIModel.objects.update_or_create(
            model="expensive-output",
            defaults={
                "label": "Expensive output",
                "provider": "openai",
                "input_weight": 1,
                "output_weight": 50,
                "cache_read_weight": 1,
                "active": True,
            },
        )
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 1000, "credits_weekly": 1000},
        )
        self.settings.limits_enabled = True
        self.settings.grace_buffer_credits = 0
        self.settings.save()

        quota = check_quota(self.user, requested_model="expensive-output")

        self.assertEqual(quota["suggested_max_output_tokens"], 20)

    def test_suggested_output_tokens_reserve_estimated_input_cost(self):
        AIModel.objects.update_or_create(
            model="balanced-model",
            defaults={
                "label": "Balanced model",
                "provider": "openai",
                "input_weight": 10,
                "output_weight": 10,
                "cache_read_weight": 1,
                "active": True,
            },
        )
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 250, "credits_weekly": 250},
        )
        self.settings.limits_enabled = True
        self.settings.grace_buffer_credits = 0
        self.settings.save()

        quota = check_quota(
            self.user,
            requested_model="balanced-model",
            estimated_input_tokens=5,
        )

        self.assertEqual(quota["suggested_max_output_tokens"], 20)

    def test_quota_preblocks_when_input_leaves_no_minimum_output_budget(self):
        AIModel.objects.update_or_create(
            model="boundary-model",
            defaults={
                "label": "Boundary model",
                "provider": "openai",
                "input_weight": 1,
                "output_weight": 1,
                "cache_read_weight": 0,
                "active": True,
            },
        )
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 100, "credits_weekly": 100},
        )
        self.settings.limits_enabled = True
        self.settings.grace_buffer_credits = 0
        self.settings.save()

        quota = check_quota(
            self.user,
            requested_model="boundary-model",
            estimated_input_tokens=100,
        )

        self.assertFalse(quota["allowed"])
        self.assertEqual(quota["exceeded_window"], "input")

    def test_null_session_limit_only_enforces_weekly_window(self):
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": None, "credits_weekly": 100},
        )
        AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model_id="gpt-5.6-luna",
            credits=100,
            request_id="weekly-only-limit",
        )
        self.settings.limits_enabled = True
        self.settings.grace_buffer_credits = 0
        self.settings.save()

        quota = check_quota(self.user, scope="explain")

        self.assertFalse(quota["allowed"])
        self.assertEqual(quota["exceeded_window"], "weekly")
        self.assertIsNone(quota["usage"]["session"]["limit"])
        self.assertEqual(quota["usage"]["weekly"]["limit"], 100)
        self.assertNotIn("unlimited", quota["usage"])

    def test_disabled_limits_do_not_reduce_output_budget_or_trigger_fallback(self):
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 0, "credits_weekly": 0},
        )
        self.settings.limits_enabled = False
        self.settings.grace_buffer_credits = 0
        self.settings.save()

        quota = check_quota(
            self.user,
            scope="chat",
            requested_model="gpt-5.6-luna",
            available_providers=["openai"],
        )

        self.assertTrue(quota["allowed"])
        self.assertTrue(quota["would_block"])
        self.assertEqual(quota["quota_tier"], "normal")
        self.assertIsNone(quota["fallback_grant_id"])
        self.assertEqual(quota["suggested_max_output_tokens"], 4096)
        self.assertNotIn("unlimited", quota["usage"])
        for window in (quota["usage"]["session"], quota["usage"]["weekly"]):
            self.assertNotIn("unlimited", window)
            self.assertIsNone(window["limit"])
            self.assertIsNone(window["remaining"])
            self.assertIsNone(window["resets_at"])

    def test_usage_summary_is_unlimited_while_limits_are_disabled(self):
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 100, "credits_weekly": 500},
        )
        AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model_id="gpt-5.6-luna",
            credits=25,
            request_id="disabled-limits-summary",
        )
        self.settings.limits_enabled = False
        self.settings.save(update_fields=("limits_enabled",))

        summary = get_usage_summary(self.user)

        self.assertNotIn("unlimited", summary)
        self.assertFalse(summary["exhausted"])
        self.assertIsNone(summary["blocked_until"])
        for window in (summary["session"], summary["weekly"]):
            self.assertEqual(window["used"], Decimal("25"))
            self.assertNotIn("unlimited", window)
            self.assertIsNone(window["limit"])
            self.assertIsNone(window["remaining"])
            self.assertIsNone(window["resets_at"])

    def test_zero_output_weight_uses_default_output_cap(self):
        AIModel.objects.update_or_create(
            model="free-output",
            defaults={
                "label": "Free output",
                "provider": "openai",
                "input_weight": 1,
                "output_weight": 0,
                "cache_read_weight": 0,
                "active": True,
            },
        )

        quota = check_quota(self.user, requested_model="free-output")

        self.assertEqual(quota["suggested_max_output_tokens"], 4096)

    def test_quota_resolves_default_when_requested_model_is_inactive(self):
        AIModel.objects.filter(model="gpt-5.6-terra").update(active=False)

        quota = check_quota(
            self.user,
            requested_model="gpt-5.6-terra",
        )

        self.assertTrue(quota["allowed"])
        self.assertEqual(quota["resolved_model"], "gpt-5.6-luna")
        self.assertEqual(quota["resolved_provider"], "openai")

    def test_quota_fails_closed_when_no_eligible_model_is_active(self):
        AIModel.objects.filter(minimum_account_level=AccountLevel.BASIC).update(active=False)

        quota = check_quota(self.user, requested_model="gpt-5.6-terra")

        self.assertFalse(quota["allowed"])
        self.assertEqual(quota["exceeded_window"], "model_unavailable")
        self.assertIsNone(quota["resolved_model"])

    def test_malformed_message_parts_do_not_drop_usage_report(self):
        conversation_id = "9a59cb45-e55b-4853-b3b4-698e84c76221"

        event, created = record_usage(
            user=self.user,
            scope="chat",
            model="gpt-5.6-terra",
            input_tokens=5,
            request_id="malformed-message",
            conversation_id=conversation_id,
            messages=[
                {
                    "role": "user",
                    "parts": [
                        {"type": "text", "text": None},
                        {"type": "text", "text": "valid title"},
                    ],
                }
            ],
        )

        self.assertTrue(created)
        self.assertGreater(event.credits, 0)
        self.assertEqual(AIChatConversation.objects.get(pk=conversation_id).title, "valid title")

    def test_null_message_fields_are_normalized_and_usage_is_recorded(self):
        conversation_id = "cb1e2ee7-dd72-47bc-b8e4-c2fc963d129c"

        event, created = record_usage(
            user=self.user,
            scope="chat",
            model="gpt-5.6-terra",
            input_tokens=5,
            request_id="null-message-fields",
            conversation_id=conversation_id,
            messages=[{"id": None, "role": None, "parts": None, "model": None}],
        )

        message = AIChatConversation.objects.get(pk=conversation_id).messages.get()
        self.assertTrue(created)
        self.assertGreater(event.credits, 0)
        self.assertTrue(message.message_id.startswith("auto-"))
        self.assertEqual(message.role, "unknown")
        self.assertEqual(message.content, [])
        self.assertIsNone(message.model)

    def test_chat_message_deltas_append_without_replacing_history(self):
        conversation_id = "27af06fb-0521-4885-ac1e-713820631a8e"
        for request_id, message_id, text in (
            ("delta-one", "message-one", "Pierwsza"),
            ("delta-two", "message-two", "Druga"),
        ):
            record_usage(
                user=self.user,
                scope="chat",
                model="gpt-5.6-terra",
                input_tokens=1,
                request_id=request_id,
                conversation_id=conversation_id,
                metadata={"messages_mode": "append"},
                messages=[
                    {
                        "id": message_id,
                        "role": "user",
                        "parts": [{"type": "text", "text": text}],
                    }
                ],
            )

        messages = AIChatMessage.objects.filter(conversation_id=conversation_id).order_by("order")
        self.assertEqual(list(messages.values_list("message_id", flat=True)), ["message-one", "message-two"])
        self.assertEqual(list(messages.values_list("order", flat=True)), [0, 1])

    def test_idless_append_retry_replaces_matching_message(self):
        conversation_id = "61b4cc89-95a3-4bdf-aaf5-b1e944ae9fcb"
        message = {"role": "user", "parts": [{"type": "text", "text": "Powtórz"}]}
        for request_id in ("idless-one", "idless-two"):
            record_usage(
                user=self.user,
                scope="chat",
                model="gpt-5.6-terra",
                input_tokens=1,
                request_id=request_id,
                conversation_id=conversation_id,
                metadata={"messages_mode": "append"},
                messages=[message],
            )

        self.assertEqual(AIChatMessage.objects.filter(conversation_id=conversation_id).count(), 1)

    def test_reset_is_when_enough_old_usage_expires(self):
        now = timezone.now()
        first = AIUsageEvent.objects.create(
            user=self.user, scope="chat", model_id="gpt-5.6-terra", credits=60, request_id="one"
        )
        second = AIUsageEvent.objects.create(
            user=self.user, scope="chat", model_id="gpt-5.6-terra", credits=60, request_id="two"
        )
        AIUsageEvent.objects.filter(pk=first.pk).update(created_at=now - timedelta(hours=4))
        AIUsageEvent.objects.filter(pk=second.pk).update(created_at=now - timedelta(hours=2))
        first.refresh_from_db()
        self.assertEqual(
            _reset_at(self.user, SESSION_WINDOW, Decimal("100"), Decimal("120"), now),
            first.created_at + SESSION_WINDOW,
        )

    def test_usage_summary_shows_next_credit_refresh_below_limit(self):
        self.settings.limits_enabled = True
        self.settings.save(update_fields=("limits_enabled",))
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 100, "credits_weekly": 100},
        )
        event = AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model_id="gpt-5.6-terra",
            credits=10,
            request_id="next-refresh",
        )

        summary = get_usage_summary(self.user, 7)

        self.assertEqual(
            summary["session"]["resets_at"],
            event.created_at + SESSION_WINDOW,
        )

    def test_under_limit_quota_does_not_scan_reset_events(self):
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 100, "credits_weekly": 100},
        )
        AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model_id="gpt-5.6-terra",
            credits=1,
            request_id="under-limit",
        )

        with CaptureQueriesContext(connection) as queries:
            quota = check_quota(self.user, requested_model="gpt-5.6-terra")

        self.assertTrue(quota["allowed"])
        self.assertFalse(
            any('ORDER BY "ai_aiusageevent"."created_at" ASC' in query["sql"] for query in queries.captured_queries)
        )

    def test_exhausted_user_receives_unlimited_throttled_fallback_hints(self):
        self.settings.limits_enabled = True
        self.settings.fallback_model_id = "gpt-5.6-luna"
        self.settings.fallback_throttle_seconds = 15
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 10, "credits_weekly": 10},
        )
        AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model_id="gpt-5.6-terra",
            credits=10,
            request_id="normal-quota",
        )

        quota = check_quota(self.user, scope="hint")

        self.assertTrue(quota["allowed"])
        self.assertTrue(quota["would_block"])
        self.assertEqual(quota["quota_tier"], "fallback")
        self.assertEqual(quota["fallback_model"], "gpt-5.6-luna")
        self.assertEqual(
            quota["suggested_max_output_tokens"],
            self.settings.fallback_max_output_tokens,
        )
        self.assertIsNotNone(quota["fallback_grant_id"])

        AIFallbackGrant.objects.filter(pk=quota["fallback_grant_id"]).update(
            issued_at=timezone.now() - timedelta(seconds=16)
        )

        self.assertTrue(check_quota(self.user, scope="hint")["allowed"])

    def test_exhausted_user_is_blocked_when_fallback_is_disabled(self):
        self.settings.limits_enabled = True
        self.settings.fallback_model = None
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 0, "credits_weekly": 0},
        )
        AIFallbackGrant.objects.create(user=self.user, model_id="gpt-5.6-luna")

        quota = check_quota(
            self.user,
            scope="chat",
            requested_model="gpt-5.6-terra",
        )
        summary = get_usage_summary(self.user)

        self.assertFalse(quota["allowed"])
        self.assertEqual(quota["quota_tier"], "normal")
        self.assertIn(quota["exceeded_window"], {"session", "weekly"})
        self.assertIsNone(quota["fallback_model"])
        self.assertIsNone(quota["fallback_grant_id"])
        self.assertIsNone(quota["fallback_resets_at"])
        self.assertIsNone(summary["fallback_model"])
        self.assertIsNone(summary["fallback_resets_at"])

    def test_input_preblocked_hint_does_not_enter_fallback_tier(self):
        self.settings.limits_enabled = True
        self.settings.grace_buffer_credits = 0
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 10, "credits_weekly": 10},
        )

        quota = check_quota(
            self.user,
            estimated_input_tokens=100,
            scope="hint",
            requested_model="gpt-5.6-terra",
        )

        self.assertFalse(quota["allowed"])
        self.assertEqual(quota["exceeded_window"], "input")
        self.assertEqual(quota["quota_tier"], "normal")
        self.assertIsNone(quota["fallback_model"])

    def test_exhausted_user_receives_throttled_fallback_chat(self):
        self.settings.limits_enabled = True
        self.settings.fallback_model_id = "gpt-5.6-luna"
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 0, "credits_weekly": 0},
        )

        quota = check_quota(self.user, scope="chat")

        self.assertTrue(quota["allowed"])
        self.assertEqual(quota["quota_tier"], "fallback")
        self.assertEqual(quota["resolved_model"], "gpt-5.6-luna")
        self.assertIsNotNone(quota["fallback_grant_id"])

        event, _ = record_usage(
            user=self.user,
            scope="chat",
            model="gpt-5.6-luna",
            output_tokens=1,
            request_id="approved-fallback-chat",
            fallback_grant_id=quota["fallback_grant_id"],
        )

        self.assertTrue(event.quota_exempt)

    def test_unreserved_exempt_event_does_not_throttle_fallback(self):
        self.settings.limits_enabled = True
        self.settings.fallback_throttle_seconds = 15
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 10, "credits_weekly": 10},
        )
        AIUsageEvent.objects.create(
            user=self.user, scope="chat", model_id="gpt-5.6-terra", credits=10, request_id="quota"
        )
        AIUsageEvent.objects.create(
            user=self.user,
            scope="hint",
            model_id="gpt-5.6-luna",
            credits=50,
            request_id="fallback-hint",
            quota_exempt=True,
        )

        quota = check_quota(self.user, scope="hint")

        self.assertTrue(quota["allowed"])
        self.assertIsNotNone(quota["fallback_grant_id"])

    def test_only_the_exact_throttled_fallback_is_quota_exempt(self):
        self.settings.limits_enabled = True
        self.settings.fallback_model_id = "gpt-5.6-luna"
        self.settings.fallback_throttle_seconds = 30
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 1, "credits_weekly": 1},
        )
        AIUsageEvent.objects.create(
            user=self.user, scope="chat", model_id="gpt-5.6-terra", credits=1, request_id="spent"
        )

        fallback_quota = check_quota(self.user, scope="hint")

        expensive, _ = record_usage(
            user=self.user,
            scope="hint",
            model="claude-fable-5",
            output_tokens=1,
            request_id="forged-expensive-hint",
        )
        approved, _ = record_usage(
            user=self.user,
            scope="hint",
            model="gpt-5.6-luna",
            output_tokens=1,
            request_id="approved-fallback-hint",
            fallback_grant_id=fallback_quota["fallback_grant_id"],
        )
        throttled, _ = record_usage(
            user=self.user,
            scope="hint",
            model="gpt-5.6-luna",
            output_tokens=1,
            request_id="throttled-fallback-hint",
        )

        self.assertFalse(expensive.quota_exempt)
        self.assertTrue(approved.quota_exempt)
        self.assertFalse(throttled.quota_exempt)

    def test_foreign_conversation_is_ignored_but_usage_is_billed(self):
        owner = User.objects.create_user(email="conversation-owner@example.com")
        conversation = AIChatConversation.objects.create(user=owner)

        event, created = record_usage(
            user=self.user,
            scope="chat",
            model="gpt-5.6-terra",
            input_tokens=10,
            request_id="foreign-conversation",
            conversation_id=conversation.id,
            messages=[{"role": "user", "parts": [{"type": "text", "text": "Nie moje"}]}],
        )

        self.assertTrue(created)
        self.assertGreater(event.credits, 0)
        self.assertIsNone(event.conversation_id)
        self.assertFalse(conversation.messages.exists())

    def test_inaccessible_quiz_is_ignored_but_history_and_usage_are_kept(self):
        owner = User.objects.create_user(email="private-quiz-owner@example.com")
        private_quiz = Quiz.objects.create(
            title="Private",
            creator=owner,
            folder=owner.root_folder,
            visibility=0,
        )
        conversation_id = "8b155ec2-267c-4f95-8492-6655400accd9"

        event, created = record_usage(
            user=self.user,
            scope="chat",
            model="gpt-5.6-terra",
            input_tokens=10,
            request_id="inaccessible-quiz",
            conversation_id=conversation_id,
            quiz_id=private_quiz.id,
            messages=[{"role": "user", "parts": [{"type": "text", "text": "Keep me"}]}],
        )

        self.assertTrue(created)
        self.assertGreater(event.credits, 0)
        self.assertIsNone(event.quiz_id)
        self.assertEqual(str(event.conversation_id), conversation_id)
        self.assertIsNone(event.conversation.quiz_id)
        self.assertEqual(event.conversation.messages.count(), 1)

    def test_input_preblock_returns_reset_when_existing_usage_can_expire(self):
        self.settings.limits_enabled = True
        self.settings.grace_buffer_credits = 0
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 100, "credits_weekly": 100},
        )
        AIUsageEvent.objects.create(
            user=self.user, scope="chat", model_id="gpt-5.6-terra", credits=80, request_id="used"
        )

        quota = check_quota(self.user, estimated_input_tokens=30, requested_model="gpt-5.6-luna")

        self.assertFalse(quota["allowed"])
        self.assertEqual(quota["exceeded_window"], "input")
        self.assertIsNotNone(quota["resets_at"])

    def test_fallback_usage_does_not_delay_normal_quota_reset(self):
        AIUsageEvent.objects.create(
            user=self.user,
            scope="hint",
            model_id="gpt-5.6-luna",
            credits=50,
            request_id="fallback-hint",
            quota_exempt=True,
        )

        summary = get_usage_summary(self.user, 7)

        self.assertEqual(summary["session"]["used"], Decimal("0"))
        self.assertNotIn("hint_rescue", summary)

    def test_usage_summary_exposes_server_computed_block_state(self):
        self.settings.limits_enabled = True
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 10, "credits_weekly": 10},
        )
        AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model_id="gpt-5.6-terra",
            credits=10,
            request_id="summary-block",
        )

        summary = get_usage_summary(self.user, 30)

        self.assertTrue(summary["exhausted"])
        self.assertIsNotNone(summary["blocked_until"])
        self.assertEqual(summary["fallback_model"], self.settings.fallback_model_id)

    def test_usage_summary_omits_inactive_fallback_model(self):
        AIModel.objects.filter(model=self.settings.fallback_model_id).update(active=False)

        summary = get_usage_summary(self.user, 30)

        self.assertIsNone(summary["fallback_model"])

    def test_prune_adds_new_rollup_to_existing_aggregate(self):
        event = AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model_id="gpt-5.6-terra",
            credits=Decimal("5"),
            input_tokens=3,
            request_id="old-rollup",
            cache_write_tokens=4,
        )
        old_time = timezone.now() - timedelta(days=2)
        AIUsageEvent.objects.filter(pk=event.pk).update(created_at=old_time)
        AIUsageDailyAggregate.objects.create(
            user=self.user,
            date=timezone.localdate(old_time),
            scope="chat",
            model_id="gpt-5.6-terra",
            credits=Decimal("7"),
            input_tokens=2,
            cache_write_tokens=6,
            event_count=1,
        )

        call_command("prune_ai_usage", usage_retention_days=1)

        aggregate = AIUsageDailyAggregate.objects.get(
            user=self.user,
            date=timezone.localdate(old_time),
            scope="chat",
            model_id="gpt-5.6-terra",
        )
        self.assertEqual(aggregate.credits, Decimal("12"))
        self.assertEqual(aggregate.input_tokens, 5)
        self.assertEqual(aggregate.cache_write_tokens, 10)
        self.assertEqual(aggregate.event_count, 2)

    def test_inactive_model_is_removed_and_cannot_be_used_as_fallback(self):
        AIModel.objects.filter(model="gpt-5.6-luna").update(active=False)
        AIModel.objects.update_or_create(
            model="gpt-5.6-terra",
            defaults={
                "label": "GPT-5.6 Terra",
                "provider": "openai",
                "input_weight": 1,
                "output_weight": 1,
                "cache_read_weight": 1,
                "active": True,
            },
        )
        self.settings.limits_enabled = True
        self.settings.fallback_model_id = "gpt-5.6-luna"
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 0, "credits_weekly": 0},
        )

        quota = check_quota(self.user, scope="hint")

        self.assertNotIn("gpt-5.6-luna", quota["active_models"])
        self.assertFalse(quota["allowed"])
        self.assertEqual(quota["exceeded_window"], "model_unavailable")
        self.assertIsNone(quota["fallback_model"])
        self.assertIsNone(quota["fallback_grant_id"])

    def test_fallback_admission_is_reserved_before_usage_is_reported(self):
        self.settings.limits_enabled = True
        self.settings.fallback_throttle_seconds = 30
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 1, "credits_weekly": 1},
        )
        AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model_id="gpt-5.6-terra",
            credits=1,
            request_id="fallback-reset-source",
        )

        first = check_quota(self.user, scope="hint")
        second = check_quota(self.user, scope="hint")

        self.assertTrue(first["allowed"])
        self.assertIsNotNone(first["fallback_grant_id"])
        self.assertIsNotNone(first["fallback_resets_at"])
        self.assertEqual(
            get_usage_summary(self.user, 7)["fallback_resets_at"],
            first["fallback_resets_at"],
        )

        event, _ = record_usage(
            user=self.user,
            scope="hint",
            model=first["fallback_model"],
            output_tokens=1,
            request_id="reported-fallback-admission",
            fallback_grant_id=first["fallback_grant_id"],
        )

        self.assertTrue(event.quota_exempt)
        self.assertEqual(
            get_usage_summary(self.user, 7)["fallback_resets_at"],
            first["fallback_resets_at"],
        )
        self.assertFalse(second["allowed"])
        self.assertEqual(second["exceeded_window"], "fallback_throttle")
        self.assertIsNone(second["fallback_grant_id"])
        self.assertIsNotNone(second["usage"]["session"]["resets_at"])

    def test_fallback_resolution_uses_exact_backend_configuration(self):
        self.settings.limits_enabled = True
        self.settings.fallback_model_id = "claude-opus-5"
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 0, "credits_weekly": 0},
        )

        quota = check_quota(self.user, scope="hint")

        self.assertTrue(quota["allowed"])
        self.assertEqual(quota["fallback_model"], "claude-opus-5")
        self.assertEqual(quota["resolved_model"], "claude-opus-5")

    def test_fallback_works_without_a_normal_candidate(self):
        self.settings.limits_enabled = True
        self.settings.fallback_model_id = "claude-opus-5"
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 0, "credits_weekly": 0},
        )

        quota = check_quota(
            self.user,
            scope="hint",
            available_providers=["anthropic"],
        )

        self.assertTrue(quota["allowed"])
        self.assertEqual(quota["resolved_model"], "claude-opus-5")

    def test_unavailable_fallback_does_not_reserve_or_throttle(self):
        self.settings.limits_enabled = True
        self.settings.fallback_model_id = "claude-opus-5"
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 0, "credits_weekly": 0},
        )

        first = check_quota(
            self.user,
            scope="hint",
            available_providers=["openai"],
        )
        second = check_quota(
            self.user,
            scope="hint",
            available_providers=["openai"],
        )

        self.assertFalse(first["allowed"])
        self.assertEqual(first["exceeded_window"], "model_unavailable")
        self.assertIsNone(first["fallback_grant_id"])
        self.assertEqual(second["exceeded_window"], "model_unavailable")
        self.assertFalse(AIFallbackGrant.objects.filter(user=self.user).exists())

    def test_fallback_grant_is_single_use_and_bound_to_model(self):
        self.settings.limits_enabled = True
        self.settings.save()
        AIAccountLimit.objects.update_or_create(
            account_type=AccountType.EMAIL,
            account_level=AccountLevel.BASIC,
            defaults={"credits_session": 0, "credits_weekly": 0},
        )
        quota = check_quota(self.user, scope="hint")

        wrong_model, _ = record_usage(
            user=self.user,
            scope="hint",
            model="gpt-5.6-terra",
            output_tokens=1,
            request_id="wrong-grant-model",
            fallback_grant_id=quota["fallback_grant_id"],
        )
        approved, _ = record_usage(
            user=self.user,
            scope="hint",
            model=quota["fallback_model"],
            output_tokens=1,
            request_id="right-grant-model",
            fallback_grant_id=quota["fallback_grant_id"],
        )
        reused, _ = record_usage(
            user=self.user,
            scope="hint",
            model=quota["fallback_model"],
            output_tokens=1,
            request_id="reused-grant",
            fallback_grant_id=quota["fallback_grant_id"],
        )

        self.assertFalse(wrong_model.quota_exempt)
        self.assertTrue(approved.quota_exempt)
        self.assertFalse(reused.quota_exempt)
