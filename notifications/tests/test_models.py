from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from notifications.models import DeliveryStatus, Notification, NotificationType
from notifications.utils import send_notification

User = get_user_model()


class NotificationModelTestCase(TestCase):
    """Tests for the Notification ORM model."""

    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

    def test_notification_creation_defaults(self):
        notification = Notification.objects.create(
            user=self.user,
            title="Test notification",
            content="Test notification message",
            notification_type=NotificationType.IN_APP,
        )

        self.assertEqual(notification.user, self.user)
        self.assertEqual(notification.content, "Test notification message")
        self.assertEqual(notification.notification_type, NotificationType.IN_APP)
        self.assertFalse(notification.is_read)
        self.assertIsNotNone(notification.created_at)
        self.assertIsNotNone(notification.updated_at)

    def test_default_ordering_is_newest_first(self):
        first = Notification.objects.create(
            user=self.user, title="First", content="x", notification_type=NotificationType.IN_APP
        )
        second = Notification.objects.create(
            user=self.user, title="Second", content="x", notification_type=NotificationType.IN_APP
        )

        ordered_ids = list(Notification.objects.values_list("id", flat=True))
        self.assertEqual(ordered_ids, [second.id, first.id])

    def test_str_representation(self):
        notification = Notification.objects.create(
            user=self.user, title="Hello", content="x", notification_type=NotificationType.IN_APP
        )
        self.assertIn("Hello", str(notification))
        self.assertIn(str(notification.id), str(notification))


class NotificationQueryTestCase(TestCase):
    """Tests for common Notification queries (per-user / read-status filtering)."""

    def setUp(self):
        self.user1 = User.objects.create_user(email="user1@example.com", password="pass123")
        self.user2 = User.objects.create_user(email="user2@example.com", password="pass123")

        Notification.objects.create(
            user=self.user1,
            title="Notification 1",
            content="Notification 1",
            notification_type=NotificationType.IN_APP,
        )
        Notification.objects.create(
            user=self.user1,
            title="Notification 2",
            content="Notification 2",
            notification_type=NotificationType.EMAIL,
            is_read=True,
        )
        Notification.objects.create(
            user=self.user2,
            title="User 2 Notification",
            content="User 2 Notification",
            notification_type=NotificationType.IN_APP,
        )

    def test_filter_by_user(self):
        self.assertEqual(Notification.objects.filter(user=self.user1).count(), 2)
        self.assertEqual(Notification.objects.filter(user=self.user2).count(), 1)

    def test_filter_unread(self):
        unread = Notification.objects.filter(user=self.user1, is_read=False)
        self.assertEqual(unread.count(), 1)
        self.assertEqual(unread.first().content, "Notification 1")

    def test_filter_read(self):
        read = Notification.objects.filter(user=self.user1, is_read=True)
        self.assertEqual(read.count(), 1)
        self.assertEqual(read.first().content, "Notification 2")


class SendNotificationUtilTestCase(TestCase):
    """Tests for the send_notification utility — the single entry point."""

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass123")

    def test_in_app_notification_is_persisted_only(self):
        with patch("notifications.utils.send_email") as mocked_send_email:
            notification = send_notification(
                user=self.user,
                title="Title",
                content="Body",
                notification_type=NotificationType.IN_APP,
            )

        self.assertIsInstance(notification, Notification)
        self.assertEqual(notification.user, self.user)
        self.assertEqual(notification.notification_type, NotificationType.IN_APP)
        # In-app records are their own delivery — marked as delivered immediately.
        self.assertEqual(notification.delivery_status, DeliveryStatus.DELIVERED)
        mocked_send_email.assert_not_called()

    def test_email_notification_persists_and_sends_email(self):
        with patch("notifications.utils.send_email") as mocked_send_email:
            mocked_send_email.return_value = True
            notification = send_notification(
                user=self.user,
                title="Title",
                content="Body",
                notification_type=NotificationType.EMAIL,
                cta_url="https://example.com",
                cta_text="Open",
                subject="Custom subject",
                reply_to=["reply@example.com"],
            )

        # Persisted record
        self.assertTrue(Notification.objects.filter(pk=notification.pk).exists())
        self.assertEqual(notification.notification_type, NotificationType.EMAIL)

        # Email transport invoked with the expected kwargs
        mocked_send_email.assert_called_once()
        kwargs = mocked_send_email.call_args.kwargs
        self.assertEqual(kwargs["recipient_list"], [self.user.email])
        self.assertEqual(kwargs["subject"], "Custom subject")
        self.assertEqual(kwargs["title"], "Title")
        self.assertEqual(kwargs["content"], "Body")
        self.assertEqual(kwargs["cta_url"], "https://example.com")
        self.assertEqual(kwargs["cta_text"], "Open")
        self.assertEqual(kwargs["reply_to"], ["reply@example.com"])

        # Delivery status flips to DELIVERED after a successful send.
        notification.refresh_from_db()
        self.assertEqual(notification.delivery_status, DeliveryStatus.DELIVERED)
        self.assertEqual(notification.delivery_error, "")

    def test_email_notification_uses_title_as_subject_by_default(self):
        with patch("notifications.utils.send_email") as mocked_send_email:
            mocked_send_email.return_value = True
            send_notification(
                user=self.user,
                title="Default subject",
                content="Body",
                notification_type=NotificationType.EMAIL,
            )

        kwargs = mocked_send_email.call_args.kwargs
        self.assertEqual(kwargs["subject"], "Default subject")

    def test_email_notification_skipped_when_user_has_no_email(self):
        self.user.email = ""
        self.user.save()

        with patch("notifications.utils.send_email") as mocked_send_email:
            notification = send_notification(
                user=self.user,
                title="Title",
                content="Body",
                notification_type=NotificationType.EMAIL,
            )

        # Record is still persisted, but the e-mail transport is skipped
        # and the notification is marked FAILED for visibility.
        self.assertTrue(Notification.objects.filter(pk=notification.pk).exists())
        mocked_send_email.assert_not_called()
        notification.refresh_from_db()
        self.assertEqual(notification.delivery_status, DeliveryStatus.FAILED)
        self.assertIn("no e-mail address", notification.delivery_error.lower())

    def test_email_notification_marked_failed_when_backend_returns_false(self):
        with patch("notifications.utils.send_email") as mocked_send_email:
            mocked_send_email.return_value = False
            notification = send_notification(
                user=self.user,
                title="Title",
                content="Body",
                notification_type=NotificationType.EMAIL,
            )

        notification.refresh_from_db()
        self.assertEqual(notification.delivery_status, DeliveryStatus.FAILED)
        self.assertNotEqual(notification.delivery_error, "")

    def test_email_notification_marked_failed_when_backend_raises(self):
        with patch("notifications.utils.send_email") as mocked_send_email:
            mocked_send_email.side_effect = RuntimeError("SMTP down")
            with self.assertRaises(RuntimeError):
                send_notification(
                    user=self.user,
                    title="Title",
                    content="Body",
                    notification_type=NotificationType.EMAIL,
                    fail_silently=False,
                )

        # Even though the exception propagates, the failure is persisted first.
        notification = Notification.objects.get(user=self.user)
        self.assertEqual(notification.delivery_status, DeliveryStatus.FAILED)
        self.assertIn("SMTP down", notification.delivery_error)

    def test_push_notification_is_persisted_without_transport(self):
        with patch("notifications.utils.send_email") as mocked_send_email:
            notification = send_notification(
                user=self.user,
                title="Push title",
                content="Push body",
                notification_type=NotificationType.PUSH,
            )

        self.assertEqual(notification.notification_type, NotificationType.PUSH)
        # Push transport is not implemented yet — the record stays PENDING until
        # a real transport is wired in, but the e-mail path must not fire.
        self.assertEqual(notification.delivery_status, DeliveryStatus.PENDING)
        mocked_send_email.assert_not_called()
