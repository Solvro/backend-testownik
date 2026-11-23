from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AdminSidebarTestCase(TestCase):
    def test_models_outside_the_sidebar_stay_reachable(self):
        staff = get_user_model().objects.create_superuser(email="admin@example.com", password="pass12345")
        self.client.force_login(staff)

        page = self.client.get(reverse("admin:index"))

        self.assertContains(page, "All applications")
        self.assertContains(page, reverse("admin:legal_legalacceptance_changelist"))
