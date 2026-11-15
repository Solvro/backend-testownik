from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from users.models import AccountLevel, AccountLevelGrant, AccountLevelGrantSource, User
from users.serializers import UserSerializer


class UserAccountLevelSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="level-profile@example.com", password="pass")

    def test_profile_serializes_active_level_and_expiration_details(self):
        expires_at = timezone.now() + timedelta(days=30)
        AccountLevelGrant.objects.create(
            user=self.user,
            level=AccountLevel.SILVER,
            source=AccountLevelGrantSource.ADMIN,
            starts_at=timezone.now(),
            expires_at=expires_at,
        )

        data = UserSerializer(self.user).data

        self.assertEqual(data["account_level"], AccountLevel.SILVER)
        self.assertEqual(data["account_level_details"]["effective_level"], AccountLevel.SILVER.value)
        self.assertEqual(data["account_level_details"]["permanent_level"], AccountLevel.BASIC.value)
        self.assertEqual(data["account_level_details"]["next_level"], AccountLevel.BASIC.value)
        serialized_expiry = data["account_level_details"]["expires_at"]
        self.assertEqual(datetime.fromisoformat(serialized_expiry.replace("Z", "+00:00")), expires_at)

    def test_permanent_level_and_indefinite_grant_have_no_expiry(self):
        self.user.account_level = AccountLevel.GOLD
        self.user.save(update_fields=["account_level"])

        data = UserSerializer(self.user).data

        self.assertEqual(data["account_level"], AccountLevel.GOLD)
        self.assertIsNone(data["account_level_details"]["expires_at"])
        self.assertIsNone(data["account_level_details"]["next_level"])
