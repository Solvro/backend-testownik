from django.contrib.auth import get_user_model
from django.test import TestCase

from notifications.models import Notification


class NotificationCreationTestCase(TestCase):
    """Test notification creation."""

    def setUp(self):
        """Create test user."""
        User = get_user_model()
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

    def test_notification_creation(self):
        """Test basic notification creation."""
        notification = Notification.objects.create(
            user=self.user, content="Test notification message", notification_type="info"
        )

        self.assertEqual(notification.user, self.user)
        self.assertEqual(notification.content, "Test notification message")
        self.assertEqual(notification.notification_type, "info")
        self.assertFalse(notification.is_read)


class NotificationRetrievalTestCase(TestCase):
    """Test notification retrieval."""

    def setUp(self):
        """Setup test users and multiple notifications."""
        User = get_user_model()
        self.user1 = User.objects.create_user(email="user1@example.com", password="pass123")
        self.user2 = User.objects.create_user(email="user2@example.com", password="pass123")

        # Create notifications for user1
        Notification.objects.create(user=self.user1, content="Notification 1", notification_type="info")
        Notification.objects.create(
            user=self.user1, content="Notification 2", notification_type="warning", is_read=True
        )

        # Create notification for user2
        Notification.objects.create(user=self.user2, content="User 2 Notification", notification_type="info")

    def test_get_user_notifications(self):
        """Test filtering notifications by user."""
        user1_notifications = Notification.objects.filter(user=self.user1)

        self.assertEqual(user1_notifications.count(), 2)

    def test_get_unread_notifications(self):
        """Test retrieving only unread notifications."""
        unread_notifications = Notification.objects.filter(user=self.user1, is_read=False)

        self.assertEqual(unread_notifications.count(), 1)
        self.assertEqual(unread_notifications.first().content, "Notification 1")

    def test_get_read_notifications(self):
        """Test retrieving only read notifications."""
        read_notifications = Notification.objects.filter(user=self.user1, is_read=True)

        self.assertEqual(read_notifications.count(), 1)
        self.assertEqual(read_notifications.first().content, "Notification 2")


class NotificationUpdateTestCase(TestCase):
    """Test notification updates."""

    def setUp(self):
        """Setup test user and notification."""
        User = get_user_model()
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")
        self.notification = Notification.objects.create(
            user=self.user, content="Test notification", notification_type="info"
        )

    def test_mark_notification_as_read(self):
        """Test updating the is_read field."""
        self.assertFalse(self.notification.is_read)

        self.notification.is_read = True
        self.notification.save()

        refreshed = Notification.objects.get(pk=self.notification.pk)
        self.assertTrue(refreshed.is_read)

    def test_update_notification_content(self):
        """Test updating the notification content."""
        new_content = "Updated notification content"
        self.notification.content = new_content
        self.notification.save()

        refreshed = Notification.objects.get(pk=self.notification.pk)
        self.assertEqual(refreshed.content, new_content)


class NotificationDeletionTestCase(TestCase):
    """Test notification deletion."""

    def setUp(self):
        """Setup test user and notification."""
        User = get_user_model()
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")
        self.notification = Notification.objects.create(
            user=self.user, content="Test notification", notification_type="info"
        )

    def test_delete_notification(self):
        """Test deleting a single notification."""
        notification_id = self.notification.pk
        self.notification.delete()

        with self.assertRaises(Notification.DoesNotExist):
            Notification.objects.get(pk=notification_id)
