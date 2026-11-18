from django.contrib.admin import helpers
from django.contrib.auth import get_user_model
from django.forms import modelform_factory
from django.test import TestCase
from django.urls import reverse

from users.admin import UserAdminForm

User = get_user_model()


class BanReasonFormTests(TestCase):
    def form_errors(self, **changes):
        user = User.objects.create_user(email="student@example.com")
        form_class = modelform_factory(User, form=UserAdminForm, fields=["is_banned", "ban_reason"])
        form = form_class(data=changes, instance=user)
        form.is_valid()
        return form.errors

    def test_ban_without_a_reason_is_rejected(self):
        self.assertIn("ban_reason", self.form_errors(is_banned=True, ban_reason="   "))

    def test_ban_with_a_reason_is_accepted(self):
        self.assertNotIn("ban_reason", self.form_errors(is_banned=True, ban_reason="Spam"))

    def test_active_user_needs_no_reason(self):
        self.assertNotIn("ban_reason", self.form_errors(is_banned=False, ban_reason=""))


class BanUsersActionTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser(email="admin@example.com", password="pass12345"))
        self.student = User.objects.create_user(email="student@example.com")

    def post(self, **extra):
        data = {"action": "ban_users", helpers.ACTION_CHECKBOX_NAME: [str(self.student.pk)], **extra}
        return self.client.post(reverse("admin:users_user_changelist"), data)

    def test_action_asks_for_a_reason_before_banning(self):
        response = self.post(index="0")

        self.assertContains(response, 'name="reason"')
        self.student.refresh_from_db()
        self.assertFalse(self.student.is_banned)

    def test_empty_reason_does_not_ban(self):
        response = self.post(apply="1", reason="   ")

        self.assertContains(response, "This field is required")
        self.student.refresh_from_db()
        self.assertFalse(self.student.is_banned)

    def test_reason_is_saved_with_the_ban(self):
        self.post(apply="1", reason="Spam w komentarzach")

        self.student.refresh_from_db()
        self.assertTrue(self.student.is_banned)
        self.assertEqual(self.student.ban_reason, "Spam w komentarzach")
