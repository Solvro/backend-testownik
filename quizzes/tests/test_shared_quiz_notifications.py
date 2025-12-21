from unittest.mock import Mock, patch

from django.conf import settings
from django.test import TransactionTestCase

from quizzes.services.notifications import (
    _create_quiz_shared_email,
    _sanitize_email_header,
    notify_quiz_shared_to_groups,
    notify_quiz_shared_to_users,
    should_send_notification,
)


class ShouldSendNotificationTests(TransactionTestCase):
    """Testy funkcji should_send_notification"""

    def test_returns_true_when_user_has_email_and_no_settings(self):
        """Zwraca True gdy użytkownik ma email i brak atrybutu settings"""
        user = Mock(spec=["email"])
        user.email = "user@example.com"

        result = should_send_notification(user)

        self.assertTrue(result)

    def test_returns_false_when_user_has_no_email(self):
        """Zwraca False gdy użytkownik nie ma emaila"""
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

    def test_returns_false_when_notify_quiz_shared_is_false(self):
        """Zwraca False gdy notify_quiz_shared jest False"""
        user = Mock()
        user.email = "user@example.com"
        user.settings = Mock()
        user.settings.notify_quiz_shared = False

        result = should_send_notification(user)

        self.assertFalse(result)

    def test_returns_true_when_notify_quiz_shared_is_true(self):
        """Zwraca True gdy notify_quiz_shared jest True"""
        user = Mock()
        user.email = "user@example.com"
        user.settings = Mock()
        user.settings.notify_quiz_shared = True

        result = should_send_notification(user)

        self.assertTrue(result)


class CreateQuizSharedEmailTests(TransactionTestCase):
    """Testy funkcji _create_quiz_shared_email"""

    @patch("quizzes.services.notifications.render_to_string")
    def test_creates_email_with_correct_subject(self, mock_render):
        mock_render.side_effect = ["text content", "html content"]
        mock_quiz = Mock()
        mock_quiz.safe_title = "Test Quiz"
        mock_user = Mock()
        mock_user.email = "user@example.com"

        email = _create_quiz_shared_email(mock_quiz, mock_user)

        self.assertEqual(email.subject, 'Quiz "Test Quiz" został Ci udostępniony')

    @patch("quizzes.services.notifications.render_to_string")
    def test_creates_email_with_correct_recipient(self, mock_render):
        mock_render.side_effect = ["text content", "html content"]
        mock_quiz = Mock()
        mock_quiz.safe_title = "Test Quiz"
        mock_user = Mock()
        mock_user.email = "user@example.com"

        email = _create_quiz_shared_email(mock_quiz, mock_user)

        self.assertEqual(email.to, ["user@example.com"])

    @patch("quizzes.services.notifications.render_to_string")
    def test_creates_email_with_correct_from_email(self, mock_render):
        mock_render.side_effect = ["text content", "html content"]
        mock_quiz = Mock()
        mock_quiz.safe_title = "Test Quiz"
        mock_user = Mock()
        mock_user.email = "user@example.com"

        email = _create_quiz_shared_email(mock_quiz, mock_user)

        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)

    @patch("quizzes.services.notifications.render_to_string")
    def test_creates_email_with_html_alternative(self, mock_render):
        mock_render.side_effect = ["text content", "html content"]
        mock_quiz = Mock()
        mock_quiz.safe_title = "Test Quiz"
        mock_user = Mock()
        mock_user.email = "user@example.com"

        email = _create_quiz_shared_email(mock_quiz, mock_user)

        self.assertEqual(len(email.alternatives), 1)
        self.assertEqual(email.alternatives[0], ("html content", "text/html"))


class NotifyQuizSharedToUsersTests(TransactionTestCase):
    """Testy funkcji notify_quiz_shared_to_users"""

    @patch("quizzes.services.notifications._create_quiz_shared_email")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_sends_email_when_should_send_returns_true(self, mock_should_send, mock_create_email):
        mock_should_send.return_value = True
        mock_email = Mock()
        mock_create_email.return_value = mock_email
        mock_quiz = Mock()
        mock_user = Mock()

        notify_quiz_shared_to_users(mock_quiz, mock_user)

        mock_create_email.assert_called_once_with(mock_quiz, mock_user)
        mock_email.send.assert_called_once_with(fail_silently=True)

    @patch("quizzes.services.notifications._create_quiz_shared_email")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_does_not_send_email_when_should_send_returns_false(self, mock_should_send, mock_create_email):
        mock_should_send.return_value = False
        mock_quiz = Mock()
        mock_user = Mock()

        notify_quiz_shared_to_users(mock_quiz, mock_user)

        mock_create_email.assert_not_called()


class NotifyQuizSharedToGroupsTests(TransactionTestCase):
    """Testy funkcji notify_quiz_shared_to_groups"""

    @patch("quizzes.services.notifications.get_connection")
    @patch("quizzes.services.notifications._create_quiz_shared_email")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_sends_emails_to_all_eligible_group_members(self, mock_should_send, mock_create_email, mock_get_connection):
        mock_should_send.return_value = True
        mock_connection = Mock()
        mock_get_connection.return_value = mock_connection
        mock_email = Mock()
        mock_create_email.return_value = mock_email

        mock_quiz = Mock()
        user1 = Mock()
        user2 = Mock()
        mock_group = Mock()
        mock_group.members.all.return_value = [user1, user2]

        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        self.assertEqual(mock_create_email.call_count, 2)
        self.assertEqual(mock_email.send.call_count, 2)

    @patch("quizzes.services.notifications.get_connection")
    @patch("quizzes.services.notifications._create_quiz_shared_email")
    @patch("quizzes.services.notifications.should_send_notification")
    def test_skips_users_who_should_not_receive_notification(
        self, mock_should_send, mock_create_email, mock_get_connection
    ):
        mock_should_send.side_effect = [True, False, True]
        mock_connection = Mock()
        mock_get_connection.return_value = mock_connection
        mock_email = Mock()
        mock_create_email.return_value = mock_email

        mock_quiz = Mock()
        mock_group = Mock()
        mock_group.members.all.return_value = [Mock(), Mock(), Mock()]

        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        self.assertEqual(mock_create_email.call_count, 2)

    @patch("quizzes.services.notifications.get_connection")
    def test_handles_empty_group(self, mock_get_connection):
        mock_connection = Mock()
        mock_get_connection.return_value = mock_connection

        mock_quiz = Mock()
        mock_group = Mock()
        mock_group.members.all.return_value = []

        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        mock_get_connection.assert_called_once_with(fail_silently=True)


class EdgeCaseTests(TransactionTestCase):
    """Testy edge case'ów"""

    @patch("quizzes.services.notifications.render_to_string")
    def test_handles_empty_quiz_title(self, mock_render):
        mock_render.side_effect = ["text", "html"]
        mock_quiz = Mock()
        mock_quiz.safe_title = ""
        mock_user = Mock()
        mock_user.email = "user@example.com"

        email = _create_quiz_shared_email(mock_quiz, mock_user)

        self.assertEqual(email.subject, 'Quiz "" został Ci udostępniony')

    @patch("quizzes.services.notifications.render_to_string")
    def test_handles_unicode_in_quiz_title(self, mock_render):
        mock_render.side_effect = ["text", "html"]
        mock_quiz = Mock()
        mock_quiz.safe_title = "Quiz z polskimi znakami: żółć ąęśćń"
        mock_user = Mock()
        mock_user.email = "user@example.com"

        email = _create_quiz_shared_email(mock_quiz, mock_user)

        self.assertIn("żółć", email.subject)

    @patch("quizzes.services.notifications.EmailMultiAlternatives")
    @patch("quizzes.services.notifications.render_to_string")
    def test_fail_silently_parameter_is_passed(self, mock_render, mock_email_class):
        mock_render.side_effect = ["text", "html"]
        mock_email = Mock()
        mock_email_class.return_value = mock_email

        mock_quiz = Mock()
        mock_quiz.title = "Test"
        mock_user = Mock(spec=["email"])
        mock_user.email = "user@example.com"

        notify_quiz_shared_to_users(mock_quiz, mock_user)

        mock_email.send.assert_called_once_with(fail_silently=True)


class TestSanitizeEmailHeader(TransactionTestCase):
    def test_removes_newline_characters(self):
        self.assertEqual(_sanitize_email_header("Test\nTitle"), "TestTitle")

    def test_removes_carriage_return(self):
        self.assertEqual(_sanitize_email_header("Test\rTitle"), "TestTitle")

    def test_removes_null_bytes(self):
        self.assertEqual(_sanitize_email_header("Test\x00Title"), "TestTitle")

    def test_removes_multiple_control_characters(self):
        self.assertEqual(_sanitize_email_header("Test\r\n\x00Title"), "TestTitle")

    def test_strips_whitespace(self):
        self.assertEqual(_sanitize_email_header("  Test Title  "), "Test Title")

    def test_handles_none(self):
        self.assertEqual(_sanitize_email_header(None), "")

    def test_handles_empty_string(self):
        self.assertEqual(_sanitize_email_header(""), "")


class TestCreateQuizSharedEmailSanitization(TransactionTestCase):
    @patch("quizzes.services.notifications.render_to_string")
    def test_subject_uses_sanitized_title(self, mock_render):
        """Test sprawdza, że znaki kontrolne są usuwane z tytułu w temacie emaila.

        Bez znaków \r\n tekst "Bcc:" nie stanowi zagrożenia header injection,
        ponieważ pozostaje częścią tego samego nagłówka Subject.
        """
        mock_render.side_effect = ["text", "html"]

        mock_quiz = Mock()
        mock_quiz.safe_title = "Malicious\r\nBcc: attacker@evil.com\r\nTitle"

        mock_user = Mock()
        mock_user.email = "test@example.com"

        email = _create_quiz_shared_email(mock_quiz, mock_user)

        self.assertNotIn("\r", email.subject)
        self.assertNotIn("\n", email.subject)
        # After removing control characters, all text remains in a single Subject header
        self.assertIn("MaliciousBcc: attacker@evil.comTitle", email.subject)
