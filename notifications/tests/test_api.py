from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from notifications.models import Notification, NotificationType

User = get_user_model()


class NotificationViewSetAPITestCase(APITestCase):
    """End-to-end tests for the notifications REST endpoints."""

    LIST_URL = "/api/notifications/"

    def setUp(self):
        self.user = User.objects.create_user(email="owner@example.com", password="pass12345")
        self.other_user = User.objects.create_user(email="intruder@example.com", password="pass12345")

        self.own_unread = Notification.objects.create(
            user=self.user,
            title="Own unread",
            content="content",
            notification_type=NotificationType.IN_APP,
        )
        self.own_read = Notification.objects.create(
            user=self.user,
            title="Own read",
            content="content",
            notification_type=NotificationType.IN_APP,
            is_read=True,
        )
        self.other_users_notification = Notification.objects.create(
            user=self.other_user,
            title="Not yours",
            content="content",
            notification_type=NotificationType.IN_APP,
        )

        self.client.force_authenticate(user=self.user)

    def _detail_url(self, notification):
        return f"{self.LIST_URL}{notification.id}/"

    # --- Authentication ----------------------------------------------------

    def test_anonymous_user_cannot_list(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --- List / detail scoping --------------------------------------------

    def test_list_returns_only_own_notifications(self):
        response = self.client.get(self.LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data["results"] if isinstance(response.data, dict) else response.data
        ids = {item["id"] for item in results}
        self.assertEqual(ids, {str(self.own_unread.id), str(self.own_read.id)})
        self.assertNotIn(str(self.other_users_notification.id), ids)

    def test_retrieve_own_notification(self):
        response = self.client.get(self._detail_url(self.own_unread))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(self.own_unread.id))

    def test_retrieve_exposes_expected_read_only_fields(self):
        response = self.client.get(self._detail_url(self.own_unread))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Fields the frontend needs to render/filter notifications must be present.
        for field in ("id", "title", "content", "is_read", "notification_type", "created_at", "updated_at"):
            self.assertIn(field, response.data)

    def test_retrieve_other_users_notification_returns_404(self):
        response = self.client.get(self._detail_url(self.other_users_notification))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- Filtering ---------------------------------------------------------

    def test_filter_by_is_read(self):
        response = self.client.get(f"{self.LIST_URL}?is_read=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"] if isinstance(response.data, dict) else response.data
        ids = {item["id"] for item in results}
        self.assertEqual(ids, {str(self.own_unread.id)})

    # --- Patch is_read -----------------------------------------------------

    def test_patch_marks_notification_as_read(self):
        response = self.client.patch(self._detail_url(self.own_unread), {"is_read": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.own_unread.refresh_from_db()
        self.assertTrue(self.own_unread.is_read)

    def test_patch_cannot_change_read_only_fields(self):
        response = self.client.patch(
            self._detail_url(self.own_unread),
            {"title": "Hacked", "content": "Hacked", "user": self.other_user.id},
            format="json",
        )
        # The request itself is accepted (serializer silently ignores read-only fields).
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.own_unread.refresh_from_db()
        self.assertEqual(self.own_unread.title, "Own unread")
        self.assertEqual(self.own_unread.content, "content")
        self.assertEqual(self.own_unread.user, self.user)

    def test_patch_other_users_notification_returns_404(self):
        response = self.client.patch(self._detail_url(self.other_users_notification), {"is_read": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.other_users_notification.refresh_from_db()
        self.assertFalse(self.other_users_notification.is_read)

    # --- mark-all-read action ---------------------------------------------

    def test_mark_all_read_only_affects_current_user(self):
        response = self.client.patch(f"{self.LIST_URL}mark-all-read/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

        self.own_unread.refresh_from_db()
        self.own_read.refresh_from_db()
        self.other_users_notification.refresh_from_db()

        self.assertTrue(self.own_unread.is_read)
        self.assertTrue(self.own_read.is_read)
        # The other user's unread notification must stay unread.
        self.assertFalse(self.other_users_notification.is_read)

    # --- Disabled HTTP methods --------------------------------------------

    def test_create_is_not_allowed(self):
        response = self.client.post(
            self.LIST_URL,
            {
                "title": "Forbidden",
                "content": "Should not be created",
                "notification_type": NotificationType.IN_APP,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_put_is_not_allowed(self):
        response = self.client.put(
            self._detail_url(self.own_unread),
            {
                "title": "Forbidden",
                "content": "Should not be replaced",
                "notification_type": NotificationType.IN_APP,
                "is_read": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_is_not_allowed(self):
        response = self.client.delete(self._detail_url(self.own_unread))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(Notification.objects.filter(pk=self.own_unread.pk).exists())
