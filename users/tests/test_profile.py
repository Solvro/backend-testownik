from rest_framework.test import APITestCase
from usos_api.models import Sex

from users.models import AccountType, User


class CurrentUserProfileTests(APITestCase):
    url = "/api/user/"

    def setUp(self):
        self.user = User.objects.create_user(
            email="profile@example.com", first_name="Old", last_name="Name", account_type=AccountType.EMAIL
        )
        self.client.force_authenticate(self.user)

    def test_email_user_can_update_names_and_sex(self):
        response = self.client.patch(
            self.url, {"first_name": "Anna", "last_name": "Nowak", "sex": Sex.FEMALE.value}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Anna")
        self.assertEqual(self.user.last_name, "Nowak")
        self.assertEqual(self.user.sex, Sex.FEMALE.value)
        self.assertEqual(response.data["full_name"], "Anna Nowak")

    def test_email_user_can_clear_names_without_changing_other_fields(self):
        response = self.client.patch(self.url, {"first_name": "", "last_name": ""}, format="json")

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "")
        self.assertEqual(self.user.last_name, "")
        self.assertEqual(self.user.email, "profile@example.com")

    def test_verified_users_cannot_change_identity_fields(self):
        for account_type in (AccountType.STUDENT, AccountType.LECTURER):
            self.user.account_type = account_type
            self.user.save(update_fields=["account_type"])
            for payload in ({"first_name": "Changed"}, {"last_name": "Changed"}, {"sex": Sex.FEMALE.value}):
                with self.subTest(account_type=account_type, payload=payload):
                    response = self.client.patch(self.url, payload, format="json")
                    self.assertEqual(response.status_code, 400)
                    self.user.refresh_from_db()
                    self.assertEqual(self.user.first_name, "Old")
                    self.assertEqual(self.user.last_name, "Name")
                    self.assertIsNone(self.user.sex)

    def test_verified_user_can_still_change_profile_visibility(self):
        self.user.account_type = AccountType.STUDENT
        self.user.save(update_fields=["account_type"])

        response = self.client.patch(self.url, {"hide_profile": True}, format="json")

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.hide_profile)

    def test_guest_cannot_change_any_profile_field(self):
        guest = User.objects.create_guest_user()
        self.client.force_authenticate(guest)
        for payload in ({"hide_profile": True}, {"overriden_photo_url": "https://example.com/photo.png"}):
            with self.subTest(payload=payload):
                response = self.client.patch(self.url, payload, format="json")
                self.assertEqual(response.status_code, 403)
        guest.refresh_from_db()
        self.assertFalse(guest.hide_profile)
        self.assertFalse(guest.overriden_photo_url)

    def test_invalid_identity_fields_do_not_partially_update_profile(self):
        for invalid in ({"first_name": "x" * 31}, {"last_name": "x" * 52}, {"sex": "invalid"}):
            with self.subTest(invalid=invalid):
                response = self.client.patch(self.url, {"hide_profile": True, **invalid}, format="json")
                self.assertEqual(response.status_code, 400)
                self.user.refresh_from_db()
                self.assertFalse(self.user.hide_profile)
                self.assertEqual(self.user.first_name, "Old")

    def test_email_user_cannot_escalate_privileges(self):
        response = self.client.patch(self.url, {"first_name": "Changed", "is_staff": True}, format="json")

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)
        self.assertEqual(self.user.first_name, "Old")
