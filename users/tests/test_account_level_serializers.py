from django.test import SimpleTestCase
from django.utils import timezone

from users.serializers import AccountLevelGrantCreateSerializer


class AccountLevelGrantCreateSerializerTests(SimpleTestCase):
    def test_only_silver_and_gold_levels_are_allowed(self):
        for level in ("silver", "gold"):
            with self.subTest(level=level):
                serializer = AccountLevelGrantCreateSerializer(data={"level": level, "indefinite": True})
                self.assertTrue(serializer.is_valid(), serializer.errors)

        serializer = AccountLevelGrantCreateSerializer(data={"level": "basic", "indefinite": True})
        self.assertFalse(serializer.is_valid())
        self.assertIn("level", serializer.errors)

    def test_expiry_datetime_must_include_timezone(self):
        serializer = AccountLevelGrantCreateSerializer(data={"level": "silver", "expires_at": "2030-01-01T12:00:00"})

        self.assertFalse(serializer.is_valid())
        self.assertIn("expires_at", serializer.errors)

    def test_timezone_aware_expiry_datetime_is_accepted(self):
        serializer = AccountLevelGrantCreateSerializer(
            data={"level": "silver", "expires_at": "2030-01-01T12:00:00+01:00"}
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertFalse(timezone.is_naive(serializer.validated_data["expires_at"]))
