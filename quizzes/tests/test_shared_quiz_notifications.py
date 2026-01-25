from unittest.mock import Mock, patch

from django.test import TransactionTestCase

from quizzes.services.notifications import (
    notify_quiz_shared_to_groups,
    notify_quiz_shared_to_users,
    should_send_notification,
)


class ShouldSendNotificationTests(TransactionTestCase):
    """Testy funkcji should_send_notification"""

    @patch("quizzes.services.notifications.UserSettings.objects.get_or_create")
    def test_returns_true_when_user_has_email_and_no_settings(self, mock_get_or_create):
        """Zwraca True gdy użytkownik ma email i brak atrybutu settings"""
        mock_get_or_create.return_value = (Mock(notify_quiz_shared=True), True)
        user = Mock(spec=["email"])
        user.email = "user@example.com"

        result = should_send_notification(user)

        self.assertTrue(result)

    def test_returns_false_when_user_has_no_email(self):
        """Zwraca False, gdy użytkownik nie ma emaila"""
        user = Mock()
        user.email = ""

        result = should_send_notification(user)

        self.assertFalse(result)

    def test_returns_false_when_user_email_is_none(self):
        """Zwraca False gdy email użytkownika to None"""
        user = Mock()
        user.email = None

        result = should_send_notification(user)

        self.assertFalse(result)

    @patch("quizzes.services.notifications.UserSettings.objects.get_or_create")
    def test_returns_false_when_notify_quiz_shared_is_false(self, mock_get_or_create):
        """Zwraca False gdy notify_quiz_shared jest False"""
        mock_get_or_create.return_value = (Mock(notify_quiz_shared=False), True)
        user = Mock()
        user.email = "user@example.com"

        result = should_send_notification(user)

        self.assertFalse(result)

    @patch("quizzes.services.notifications.UserSettings.objects.get_or_create")
    def test_returns_true_when_notify_quiz_shared_is_true(self, mock_get_or_create):
        """Zwraca True gdy notify_quiz_shared jest True"""
        mock_get_or_create.return_value = (Mock(notify_quiz_shared=True), True)
        user = Mock()
        user.email = "user@example.com"

        result = should_send_notification(user)

        self.assertTrue(result)


class NotifyQuizSharedToUsersTests(TransactionTestCase):
    """Testy funkcji notify_quiz_shared_to_users"""

    @patch("quizzes.services.notifications.send_quiz_shared_email_task")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_enqueues_task_when_should_send_returns_true(self, mock_should_send, mock_task):
        """Kolejkuje task gdy should_send_notification zwraca True"""
        mock_should_send.return_value = True
        mock_quiz = Mock()
        mock_quiz.id = "quiz-id"
        mock_user = Mock()
        mock_user.id = "user-id"

        notify_quiz_shared_to_users(mock_quiz, mock_user)

        mock_task.enqueue.assert_called_once_with("quiz-id", "user-id")

    @patch("quizzes.services.notifications.send_quiz_shared_email_task")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_does_not_enqueue_task_when_should_send_returns_false(self, mock_should_send, mock_task):
        """Nie kolejkuje taska gdy should_send_notification zwraca False"""
        mock_should_send.return_value = False
        mock_quiz = Mock()
        mock_user = Mock()

        notify_quiz_shared_to_users(mock_quiz, mock_user)

        mock_task.enqueue.assert_not_called()


class NotifyQuizSharedToGroupsTests(TransactionTestCase):
    """Testy funkcji notify_quiz_shared_to_groups"""

    @patch("quizzes.services.notifications.send_quiz_shared_email_task")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_enqueues_for_all_eligible_group_members(self, mock_should_send, mock_task):
        """Kolejkuje task dla wszystkich użytkowników z grupy, którzy powinni dostać powiadomienie"""
        mock_should_send.side_effect = [True, False, True]

        mock_quiz = Mock()
        mock_quiz.id = "quiz-id"

        user1 = Mock()
        user1.id = "user1"
        user2 = Mock()
        user2.id = "user2"
        user3 = Mock()
        user3.id = "user3"

        mock_group = Mock()
        mock_group.members.all.return_value = [user1, user2, user3]

        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        mock_task.enqueue.assert_any_call("quiz-id", "user1")
        mock_task.enqueue.assert_any_call("quiz-id", "user3")
        self.assertEqual(mock_task.enqueue.call_count, 2)

    @patch("quizzes.services.notifications.send_quiz_shared_email_task")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_skips_users_who_should_not_receive_notification(self, mock_should_send, mock_task):
        """Pomija użytkowników, dla których should_send_notification zwraca False"""
        mock_should_send.side_effect = [False, False, True]

        mock_quiz = Mock()
        mock_quiz.id = "quiz-id"

        user1 = Mock()
        user1.id = "user1"
        user2 = Mock()
        user2.id = "user2"
        user3 = Mock()
        user3.id = "user3"

        mock_group = Mock()
        mock_group.members.all.return_value = [user1, user2, user3]

        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        mock_task.enqueue.assert_any_call("quiz-id", "user3")
        self.assertEqual(mock_task.enqueue.call_count, 1)
