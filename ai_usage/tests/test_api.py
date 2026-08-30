from django.contrib.admin.sites import AdminSite
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from ai_usage.admin import AIChatConversationAdmin, AIChatMessageInline, AIReadOnlyAdmin, AIUsageEventAdmin
from ai_usage.models import (
    AIAccountLimit,
    AIChatConversation,
    AIModel,
    AIUsageDailyAggregate,
    AIUsageEvent,
    AIUsageSettings,
    AIUserLimitOverride,
)
from ai_usage.serializers import AIUsageSettingsSerializer
from users.models import User, UserSettings


@override_settings(INTERNAL_API_KEY="internal-test-key")
class AIUsageInternalAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="api-usage@example.com")

    def test_internal_check_rejects_missing_key(self):
        response = self.client.post("/api/ai/usage/check/", {"user_id": self.user.id}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_usage_history_admins_do_not_allow_deletion(self):
        self.assertFalse(AIUsageEventAdmin(AIUsageEvent, AdminSite()).has_delete_permission(None))
        self.assertFalse(AIReadOnlyAdmin(AIUsageDailyAggregate, AdminSite()).has_delete_permission(None))

    def test_conversation_admin_is_read_only(self):
        site = AdminSite()
        conversation_admin = AIChatConversationAdmin(AIChatConversation, site)
        message_inline = AIChatMessageInline(AIChatConversation, site)

        self.assertFalse(conversation_admin.has_add_permission(None))
        self.assertFalse(conversation_admin.has_change_permission(None))
        self.assertFalse(conversation_admin.has_delete_permission(None))
        self.assertFalse(message_inline.has_add_permission(None))
        self.assertFalse(message_inline.has_change_permission(None))
        self.assertFalse(message_inline.has_delete_permission(None))

    def test_internal_check_rejects_non_ascii_key_without_error(self):
        response = self.client.post(
            "/api/ai/usage/check/",
            {"user_id": self.user.id},
            format="json",
            HTTP_API_KEY="żółw",
        )
        self.assertEqual(response.status_code, 401)

    def test_internal_check_rejects_user_who_disabled_ai(self):
        UserSettings.objects.create(user=self.user, ai_disabled=True)

        response = self.client.post(
            "/api/ai/usage/check/",
            {"user_id": self.user.id},
            format="json",
            HTTP_API_KEY="internal-test-key",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "ai_disabled")

    def test_user_model_preference_uses_a_nullable_model_relation(self):
        self.client.force_authenticate(self.user)

        selected = self.client.patch(
            "/api/settings/",
            {"default_ai_model": "gpt-5.6-luna"},
            format="json",
        )
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.data["default_ai_model"], "gpt-5.6-luna")
        self.user.settings.refresh_from_db()
        self.assertEqual(self.user.settings.default_ai_model_id, "gpt-5.6-luna")

        inherited = self.client.patch(
            "/api/settings/",
            {"default_ai_model": None},
            format="json",
        )
        self.assertEqual(inherited.status_code, 200)
        self.assertIsNone(inherited.data["default_ai_model"])
        self.user.settings.refresh_from_db()
        self.assertIsNone(self.user.settings.default_ai_model_id)

    def test_user_cannot_select_a_model_outside_their_account_level(self):
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            "/api/settings/",
            {"default_ai_model": "gpt-5.6-sol"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("default_ai_model", response.data)

    def test_invalid_days_returns_400(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/ai/usage/me/?days=abc")
        self.assertEqual(response.status_code, 400)

    def test_admin_stats_include_pruned_daily_aggregates(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        AIUsageDailyAggregate.objects.create(
            user=self.user,
            date=timezone.localdate(),
            scope="chat",
            model_id="gpt-5.6-terra",
            credits=25,
            input_tokens=10,
            output_tokens=5,
            event_count=2,
            aborted_count=1,
            error_count=1,
        )
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/ai/usage/admin/stats/?days=30")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["totals"]["credits"], "25")
        self.assertEqual(response.data["totals"]["events"], 2)
        self.assertEqual(response.data["totals"]["aborted"], 1)
        self.assertEqual(response.data["totals"]["errors"], 1)
        self.assertEqual(
            response.data["by_model"],
            [
                {
                    "model": "gpt-5.6-terra",
                    "label": "GPT-5.6 Terra",
                    "provider": "openai",
                    "credits": "25",
                    "events": 2,
                }
            ],
        )

    def test_report_is_idempotent(self):
        payload = {
            "user_id": self.user.id,
            "scope": "chat",
            "model": "gpt-5.6-terra",
            "input_tokens": 10,
            "output_tokens": 5,
            "request_id": "api-request",
        }
        first = self.client.post("/api/ai/usage/report/", payload, format="json", HTTP_API_KEY="internal-test-key")
        second = self.client.post("/api/ai/usage/report/", payload, format="json", HTTP_API_KEY="internal-test-key")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.data["created"])

    def test_report_rejects_non_object_metadata(self):
        response = self.client.post(
            "/api/ai/usage/report/",
            {
                "user_id": self.user.id,
                "scope": "chat",
                "model": "gpt-5.6-terra",
                "request_id": "invalid-metadata",
                "metadata": [1, 2],
            },
            format="json",
            HTTP_API_KEY="internal-test-key",
        )

        self.assertEqual(response.status_code, 400)

    def test_report_uses_backend_provider_instead_of_client_metadata(self):
        response = self.client.post(
            "/api/ai/usage/report/",
            {
                "user_id": self.user.id,
                "scope": "chat",
                "model": "gpt-5.6-terra",
                "provider": "xai",
                "request_id": "provider-owned-by-backend",
            },
            format="json",
            HTTP_API_KEY="internal-test-key",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(AIUsageEvent.objects.get(request_id="provider-owned-by-backend").provider, "openai")

    def test_no_eligible_model_returns_structured_conflict(self):
        AIModel.objects.filter(minimum_account_level="basic").update(active=False)

        response = self.client.post(
            "/api/ai/usage/check/",
            {
                "user_id": self.user.id,
                "requested_model": "gpt-5.6-terra",
            },
            format="json",
            HTTP_API_KEY="internal-test-key",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["exceeded_window"], "model_unavailable")
        self.assertEqual(
            set(response.data),
            {
                "allowed",
                "would_block",
                "limits_enabled",
                "exceeded_window",
                "resets_at",
                "usage",
                "suggested_max_output_tokens",
                "quota_tier",
                "fallback_model",
                "fallback_grant_id",
                "fallback_resets_at",
                "resolved_model",
                "resolved_provider",
                "active_models",
            },
        )

    def test_invalid_scope_is_rejected(self):
        response = self.client.post(
            "/api/ai/usage/check/",
            {"user_id": self.user.id, "scope": "junk"},
            format="json",
            HTTP_API_KEY="internal-test-key",
        )

        self.assertEqual(response.status_code, 400)

    def test_quota_check_uses_default_when_requested_model_is_omitted(self):
        response = self.client.post(
            "/api/ai/usage/check/",
            {"user_id": self.user.id},
            format="json",
            HTTP_API_KEY="internal-test-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["resolved_model"], "gpt-5.6-luna")

    def test_invalid_override_does_not_create_phantom_row(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)

        response = self.client.put(
            f"/api/ai/usage/admin/users/{self.user.id}/limit/",
            {"credits_session": "not-a-number", "note": ""},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(AIUserLimitOverride.objects.filter(user=self.user).exists())

    def test_limit_caps_are_serialized_as_integers_and_reject_fractions(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)
        AIAccountLimit.objects.update_or_create(
            account_type="email",
            account_level="basic",
            defaults={"credits_session": 123, "credits_weekly": 456},
        )

        limits_response = self.client.get("/api/ai/usage/admin/limits/")
        basic_email = next(
            row for row in limits_response.data if row["account_type"] == "email" and row["account_level"] == "basic"
        )
        invalid_override = self.client.put(
            f"/api/ai/usage/admin/users/{self.user.id}/limit/",
            {"credits_session": 1.5, "credits_weekly": None, "note": ""},
            format="json",
        )

        self.assertEqual(limits_response.status_code, 200)
        self.assertEqual(basic_email["credits_session"], 123)
        self.assertIsInstance(basic_email["credits_session"], int)
        self.assertEqual(invalid_override.status_code, 400)

    def test_admin_users_searches_by_full_name(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        match = User.objects.create_user(
            email="antoni@example.com",
            first_name="Antoni",
            last_name="Czaplicki",
        )
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/ai/usage/admin/users/?q=Antoni%20Czaplicki")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.data], [str(match.id)])

    def test_admin_users_can_list_only_accounts_with_overrides(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        overridden = User.objects.create_user(email="overridden@example.com")
        User.objects.create_user(email="regular@example.com")
        AIUserLimitOverride.objects.create(user=overridden, credits_session=100)
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/ai/usage/admin/users/?overrides_only=true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.data], [str(overridden.id)])
        self.assertTrue(response.data[0]["has_override"])

    def test_admin_user_is_not_blocked_while_limits_are_disabled(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        AIUsageSettings.objects.update(limits_enabled=False, staff_bypass_limits=False)
        AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model_id="gpt-5.6-terra",
            credits=999999,
            request_id="disabled-limits-usage",
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(f"/api/ai/usage/admin/users/?q={self.user.email}")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data[0]["usage"]["exhausted"])
        self.assertIsNone(response.data[0]["usage"]["blocked_until"])
        self.assertNotIn("unlimited", response.data[0]["usage"])
        self.assertIsNone(response.data[0]["usage"]["session"]["limit"])
        self.assertIsNone(response.data[0]["usage"]["weekly"]["limit"])

    def test_admin_user_events_are_paginated(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        for index in range(3):
            AIUsageEvent.objects.create(
                user=self.user,
                scope="chat",
                model_id="gpt-5.6-terra",
                credits=1,
                request_id=f"event-{index}",
            )
        self.client.force_authenticate(self.user)

        response = self.client.get(f"/api/ai/usage/admin/users/{self.user.id}/events/?limit=2&offset=0")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNotNone(response.data["next"])

    def test_admin_can_reset_everyones_limits_without_deleting_usage(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model_id="gpt-5.6-terra",
            credits=250,
            request_id="admin-global-reset",
        )
        self.client.force_authenticate(self.user)

        response = self.client.post("/api/ai/usage/admin/limits/reset/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data["reset_at"])
        self.assertEqual(AIUsageEvent.objects.filter(request_id="admin-global-reset").count(), 1)
        usage = self.client.get("/api/ai/usage/me/?days=7")
        self.assertEqual(usage.status_code, 200)
        self.assertEqual(usage.data["session"]["used"], "0")
        self.assertEqual(usage.data["weekly"]["used"], "0")

    def test_model_bulk_update_may_omit_active_and_update_one_row(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)

        response = self.client.put(
            "/api/ai/usage/admin/models/bulk/",
            [
                {
                    "model": "gpt-5.6-sol",
                    "label": "GPT-5.6 Sol",
                    "provider": "openai",
                    "minimum_account_level": "gold",
                    "input_weight": "2.5",
                    "output_weight": "15",
                    "cached_weight": "0.25",
                }
            ],
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(AIModel.objects.get(model="gpt-5.6-sol").active)

    def test_settings_save_rejects_inactive_fallback(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)
        settings = AIUsageSettings.load()
        AIModel.objects.filter(model=settings.fallback_model_id).update(active=False)
        payload = AIUsageSettingsSerializer(settings).data
        payload["limits_enabled"] = not settings.limits_enabled

        response = self.client.put(
            "/api/ai/usage/admin/settings/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("fallback_model", response.data)

    def test_settings_can_disable_fallback(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)
        settings = AIUsageSettings.load()
        payload = AIUsageSettingsSerializer(settings).data
        payload["fallback_model"] = None

        response = self.client.put(
            "/api/ai/usage/admin/settings/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["fallback_model"])
        settings.refresh_from_db()
        self.assertIsNone(settings.fallback_model)

    def test_settings_reject_fallback_output_cap_below_provider_minimum(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)
        settings = AIUsageSettings.load()
        payload = AIUsageSettingsSerializer(settings).data
        payload["fallback_max_output_tokens"] = 1

        response = self.client.put(
            "/api/ai/usage/admin/settings/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("fallback_max_output_tokens", response.data)

    def test_model_update_rejects_deactivating_configured_fallback(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)
        fallback = AIModel.objects.get(model=AIUsageSettings.load().fallback_model_id)

        response = self.client.put(
            "/api/ai/usage/admin/models/bulk/",
            [
                {
                    "model": fallback.model,
                    "label": fallback.label,
                    "provider": fallback.provider,
                    "minimum_account_level": fallback.minimum_account_level,
                    "input_weight": str(fallback.input_weight),
                    "output_weight": str(fallback.output_weight),
                    "cached_weight": str(fallback.cached_weight),
                    "active": False,
                }
            ],
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        fallback.refresh_from_db()
        self.assertTrue(fallback.active)

    def test_bulk_models_reject_duplicate_models(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)
        row = {
            "model": "gpt-5.6-sol",
            "label": "GPT-5.6 Sol",
            "provider": "openai",
            "minimum_account_level": "gold",
            "input_weight": "2.5",
            "output_weight": "15",
            "cached_weight": "0.25",
        }

        response = self.client.put(
            "/api/ai/usage/admin/models/bulk/",
            [row, row],
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_admin_can_add_model_for_supported_provider(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/ai/usage/admin/models/",
            {
                "model": "gpt-5.7-luna",
                "label": "GPT-5.7 Luna",
                "provider": "openai",
                "minimum_account_level": "basic",
                "input_weight": "0.3",
                "output_weight": "1.5",
                "cached_weight": "0.03",
                "active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(AIModel.objects.filter(model="gpt-5.7-luna").exists())

        catalog = self.client.get("/api/ai/models/")

        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.data["default_model"], "gpt-5.6-luna")
        self.assertEqual(catalog.data["fallback_model"]["model"], "gpt-5.6-luna")
        self.assertIn("gpt-5.7-luna", {row["model"] for row in catalog.data["models"]})
        self.assertNotIn("grok-4.6", {row["model"] for row in catalog.data["models"]})

    def test_admin_can_delete_unconfigured_model(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)
        model = AIModel.objects.create(
            model="gpt-removable",
            label="GPT Removable",
            provider="openai",
            minimum_account_level="basic",
            input_weight="1",
            output_weight="1",
            cached_weight="0",
            active=True,
        )
        user_settings = UserSettings.objects.create(user=self.user, default_ai_model=model)
        event = AIUsageEvent.objects.create(
            user=self.user,
            scope="chat",
            model=model,
            credits=1,
            request_id="soft-deleted-model-usage",
        )

        response = self.client.delete(f"/api/ai/usage/admin/models/{model.model}/")

        self.assertEqual(response.status_code, 204)
        model.refresh_from_db()
        self.assertFalse(model.active)
        self.assertIsNotNone(model.deleted_at)
        self.assertEqual(AIUsageEvent.objects.get(pk=event.pk).model_id, model.model)
        self.assertNotIn(
            model.model,
            {row["model"] for row in self.client.get("/api/ai/usage/admin/models/").data},
        )
        user_settings.refresh_from_db()
        self.assertIsNone(user_settings.default_ai_model)

    def test_admin_cannot_delete_configured_model(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)
        settings = AIUsageSettings.load()

        response = self.client.delete(f"/api/ai/usage/admin/models/{settings.default_model_id}/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.data)
        self.assertTrue(AIModel.objects.filter(pk=settings.default_model_id).exists())

    def test_admin_can_update_model_identifier_containing_dots(self):
        self.user.is_superuser = True
        self.user.save(update_fields=("is_superuser",))
        self.client.force_authenticate(self.user)
        AIModel.objects.create(
            model="gpt-5.6.preview",
            label="GPT preview",
            provider="openai",
            minimum_account_level="basic",
            input_weight="1",
            output_weight="1",
            cached_weight="0",
            active=False,
        )

        response = self.client.patch(
            "/api/ai/usage/admin/models/gpt-5.6.preview/",
            {"label": "GPT Preview"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["label"], "GPT Preview")
