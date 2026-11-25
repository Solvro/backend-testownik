from datetime import timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from ai.models import AIModel
from users.models import AccountLevel, AccountLevelGrant, AccountLevelGrantSource, User, UserSettings
from users.serializers import (
    PublicUserSerializer,
    UserSettingsSerializer,
    UserTokenObtainPairSerializer,
    UserTokenRefreshSerializer,
)


class EffectiveAccountLevelSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(email="effective-level@example.com", account_level=AccountLevel.BASIC)
        self.settings = UserSettings.objects.create(user=self.user)
        self.gold_model = AIModel.objects.create(
            model="gold-only-model",
            label="Gold-only model",
            provider="openai",
            minimum_account_level=AccountLevel.GOLD,
            input_weight=1,
            output_weight=1,
            cache_read_weight=0,
        )
        self.request_context = {"request": SimpleNamespace(user=self.user)}

    def grant_gold(self, expires_at):
        return AccountLevelGrant.objects.create(
            user=self.user,
            level=AccountLevel.GOLD,
            source=AccountLevelGrantSource.ADMIN,
            starts_at=timezone.now() - timedelta(minutes=1),
            expires_at=expires_at,
        )

    def test_temporary_gold_grant_allows_selecting_gold_ai_model(self):
        self.grant_gold(timezone.now() + timedelta(days=1))
        serializer = UserSettingsSerializer(
            self.settings,
            data={"default_ai_model": self.gold_model.model},
            partial=True,
            context=self.request_context,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated_settings = serializer.save()
        self.assertEqual(updated_settings.default_ai_model, self.gold_model)

    def test_expired_gold_grant_does_not_allow_selecting_gold_ai_model(self):
        self.grant_gold(timezone.now() - timedelta(seconds=1))
        serializer = UserSettingsSerializer(
            self.settings,
            data={"default_ai_model": self.gold_model.model},
            partial=True,
            context=self.request_context,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("default_ai_model", serializer.errors)

    def test_ai_model_validation_requires_authenticated_request_context(self):
        serializer = UserSettingsSerializer(
            self.settings,
            data={"default_ai_model": self.gold_model.model},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("default_ai_model", serializer.errors)

    def test_jwt_claim_uses_temporary_effective_level(self):
        self.grant_gold(timezone.now() + timedelta(days=1))

        token = UserTokenObtainPairSerializer.get_token(self.user)

        self.assertEqual(token["account_level"], AccountLevel.GOLD)

    def test_jwt_claim_falls_back_after_temporary_level_expires(self):
        self.grant_gold(timezone.now() - timedelta(seconds=1))

        token = UserTokenObtainPairSerializer.get_token(self.user)

        self.assertEqual(token["account_level"], AccountLevel.BASIC)

    def test_refresh_uses_current_effective_level_in_new_access_token(self):
        refresh = UserTokenObtainPairSerializer.get_token(self.user)
        self.grant_gold(timezone.now() + timedelta(days=1))
        serializer = UserTokenRefreshSerializer(data={"refresh": str(refresh)})

        self.assertTrue(serializer.is_valid(), serializer.errors)
        access_token = AccessToken(serializer.validated_data["access"])

        self.assertEqual(access_token["account_level"], AccountLevel.GOLD)

    def test_public_profile_uses_temporary_effective_level(self):
        self.grant_gold(timezone.now() + timedelta(days=1))

        data = PublicUserSerializer(self.user).data

        self.assertEqual(data["account_level"], AccountLevel.GOLD)
