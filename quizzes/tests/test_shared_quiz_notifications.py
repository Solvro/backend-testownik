from unittest.mock import Mock, patch

from django.test import TransactionTestCase

from quizzes.services.notifications import (
    _send_quiz_shared_email,
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


class SendQuizSharedEmailTests(TransactionTestCase):
    """Testy funkcji _send_quiz_shared_email"""

    @patch("quizzes.services.notifications.send_email")
    def test_calls_send_email_with_correct_arguments(self, mock_send_email):
        mock_quiz = Mock()
        mock_quiz.title = "Test Quiz"
        mock_quiz.id = 123
        mock_user = Mock()
        mock_user.email = "user@example.com"
        mock_user.first_name = "Antek"

        _send_quiz_shared_email(mock_quiz, mock_user)

        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args[1]
        self.assertEqual(call_kwargs["subject"], 'Quiz "Test Quiz" został Ci udostępniony')
        self.assertEqual(call_kwargs["recipient_list"], ["user@example.com"])
        self.assertEqual(call_kwargs["title"], "Cześć Antek! 👋")
        self.assertIn('Quiz <strong>"Test Quiz"</strong>', call_kwargs["content"])
        self.assertIn("/quiz/123", call_kwargs["cta_url"])

    @patch("quizzes.services.notifications.send_email")
    def test_strips_html_in_quiz_title(self, mock_send_email):
        mock_quiz = Mock()
        mock_quiz.title = "<b>Bold</b> Quiz"
        mock_quiz.id = 123
        mock_user = Mock()
        mock_user.email = "user@example.com"
        mock_user.first_name = "Antek"

        _send_quiz_shared_email(mock_quiz, mock_user)

        call_kwargs = mock_send_email.call_args[1]
        # Check that the title inside content has HTML tags stripped
        self.assertIn("Bold Quiz", call_kwargs["content"])
        self.assertNotIn("<b>", call_kwargs["content"])


class NotifyQuizSharedToUsersTests(TransactionTestCase):
    """Testy funkcji notify_quiz_shared_to_users"""

    @patch("quizzes.services.notifications._send_quiz_shared_email")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_sends_email_when_should_send_returns_true(self, mock_should_send, mock_send_helper):
        mock_should_send.return_value = True
        mock_quiz = Mock()
        mock_user = Mock()

        notify_quiz_shared_to_users(mock_quiz, mock_user)

        mock_send_helper.assert_called_once_with(mock_quiz, mock_user)

    @patch("quizzes.services.notifications._send_quiz_shared_email")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_does_not_send_email_when_should_send_returns_false(self, mock_should_send, mock_send_helper):
        mock_should_send.return_value = False
        mock_quiz = Mock()
        mock_user = Mock()

        notify_quiz_shared_to_users(mock_quiz, mock_user)

        mock_send_helper.assert_not_called()


class NotifyQuizSharedToGroupsTests(TransactionTestCase):
    """Testy funkcji notify_quiz_shared_to_groups"""

    @patch("quizzes.services.notifications.get_connection")
    @patch("quizzes.services.notifications._send_quiz_shared_email")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_sends_emails_to_all_eligible_group_members(self, mock_should_send, mock_send_helper, mock_get_connection):
        mock_should_send.return_value = True
        mock_connection = Mock()
        mock_get_connection.return_value = mock_connection

        mock_quiz = Mock()
        user1 = Mock()
        user2 = Mock()
        mock_group = Mock()
        mock_group.members.all.return_value = [user1, user2]

        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        self.assertEqual(mock_send_helper.call_count, 2)
        mock_send_helper.assert_any_call(mock_quiz, user1, connection=mock_connection)
        mock_send_helper.assert_any_call(mock_quiz, user2, connection=mock_connection)

    @patch("quizzes.services.notifications.get_connection")
    @patch("quizzes.services.notifications._send_quiz_shared_email")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_skips_users_who_should_not_receive_notification(
        self, mock_should_send, mock_send_helper, mock_get_connection
    ):
        mock_should_send.side_effect = [True, False, True]
        mock_connection = Mock()
        mock_get_connection.return_value = mock_connection

        mock_quiz = Mock()
        mock_group = Mock()
        mock_group.members.all.return_value = [Mock(), Mock(), Mock()]

        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        self.assertEqual(mock_send_helper.call_count, 2)
