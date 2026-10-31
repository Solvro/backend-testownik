from datetime import timedelta

from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from users.models import AccountLevel, AccountLevelGrant, AccountLevelGrantSource, User


class AccountLevelAdminPermissionsApiTests(APITestCase):
    def test_authenticated_user_receives_management_permission_status(self):
        user = User.objects.create_user(email="permission-check@example.com", password="pass")
        self.client.force_authenticate(user)

        response = self.client.get(reverse("account_level_admin_permissions"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"can_manage_account_levels": False})

        permission = Permission.objects.get(content_type__app_label="users", codename="manage_account_levels")
        user.user_permissions.add(permission)
        user = User.objects.get(pk=user.pk)
        self.client.force_authenticate(user)
        response = self.client.get(reverse("account_level_admin_permissions"))
        self.assertEqual(response.data, {"can_manage_account_levels": True})

    def test_anonymous_user_cannot_check_management_permission(self):
        response = self.client.get(reverse("account_level_admin_permissions"))

        self.assertEqual(response.status_code, 401)


class AccountLevelGrantApiTests(APITestCase):
    def setUp(self):
        self.manager = User.objects.create_superuser(
            email="manager@example.com",
            password="pass",
            first_name="Manager",
            last_name="Admin",
        )
        self.user = User.objects.create_user(email="target@example.com", password="pass")
        self.client.force_authenticate(self.manager)
        self.list_url = reverse("user_account_level_grants", kwargs={"user_pk": self.user.pk})

    def test_create_and_list_grants_with_limit_offset_pagination(self):
        create_response = self.client.post(
            self.list_url,
            {"level": AccountLevel.SILVER, "duration_days": 30, "reason": "Award"},
            format="json",
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.data["level"], AccountLevel.SILVER)
        self.assertEqual(create_response.data["source"], AccountLevelGrantSource.ADMIN)
        self.assertEqual(create_response.data["reason"], "Award")

        grant = AccountLevelGrant.objects.get(pk=create_response.data["id"])
        self.assertAlmostEqual(
            (grant.expires_at - grant.starts_at).total_seconds(),
            timedelta(days=30).total_seconds(),
            delta=1,
        )

        list_response = self.client.get(self.list_url, {"limit": 1, "offset": 0})

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data["count"], 1)
        self.assertEqual(len(list_response.data["results"]), 1)
        self.assertEqual(list_response.data["results"][0]["id"], str(grant.pk))

    def test_expired_deadline_returns_validation_error(self):
        response = self.client.post(
            self.list_url,
            {"level": AccountLevel.SILVER, "expires_at": (timezone.now() - timedelta(days=1)).isoformat()},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(AccountLevelGrant.objects.exists())

    def test_detail_is_scoped_to_user(self):
        grant = AccountLevelGrant.objects.create(
            user=self.user,
            level=AccountLevel.GOLD,
            source=AccountLevelGrantSource.ADMIN,
            starts_at=timezone.now(),
        )
        other_user = User.objects.create_user(email="other-target@example.com", password="pass")

        response = self.client.get(
            reverse(
                "account_level_grant_detail",
                kwargs={"user_pk": other_user.pk, "grant_id": grant.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_detail_returns_grant_for_its_user(self):
        grant = AccountLevelGrant.objects.create(
            user=self.user,
            level=AccountLevel.GOLD,
            source=AccountLevelGrantSource.ADMIN,
            starts_at=timezone.now(),
        )

        response = self.client.get(
            reverse(
                "account_level_grant_detail",
                kwargs={"user_pk": self.user.pk, "grant_id": grant.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(grant.pk))

    def test_non_manager_cannot_list_or_grant(self):
        non_manager = User.objects.create_user(email="non-manager@example.com", password="pass")
        self.client.force_authenticate(non_manager)

        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(
            self.client.post(
                self.list_url,
                {"level": AccountLevel.SILVER, "indefinite": True},
                format="json",
            ).status_code,
            403,
        )
        self.assertFalse(AccountLevelGrant.objects.exists())

        permission = Permission.objects.get(content_type__app_label="users", codename="manage_account_levels")
        non_manager.user_permissions.add(permission)
        non_manager = User.objects.get(pk=non_manager.pk)
        self.client.force_authenticate(non_manager)
        self.assertEqual(self.client.get(self.list_url).status_code, 200)

    def test_missing_user_returns_not_found(self):
        missing_url = reverse("user_account_level_grants", kwargs={"user_pk": "00000000-0000-0000-0000-000000000001"})

        self.assertEqual(self.client.get(missing_url).status_code, 404)
        self.assertEqual(
            self.client.post(
                missing_url,
                {"level": AccountLevel.SILVER, "indefinite": True},
                format="json",
            ).status_code,
            404,
        )
