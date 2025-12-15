from unittest.mock import Mock, patch

from django.conf import settings
from django.db import transaction
from django.test import TransactionTestCase

from quizzes.services.notifications import (
    notify_quiz_shared_to_groups,
    notify_quiz_shared_to_users,
    should_send_notification,
)

from quizzes.views import SharedQuizViewSet


class SharedQuizViewSetPerformCreateTests(TransactionTestCase):
    def setUp(self):
        self.viewset = SharedQuizViewSet()
        self.mock_serializer = Mock()

    @patch("quizzes.views.notify_quiz_shared_to_users")
    @patch("quizzes.views.notify_quiz_shared_to_groups")
    def test_notification_sent_to_user_when_user_exists(self, mock_notify_groups, mock_notify_users):
        """
        Test 1: Powiadomienie wysyłane do użytkownika

        Sprawdza czy gdy shared_quiz ma przypisanego użytkownika (user),
        wywołana zostanie funkcja notify_quiz_shared_to_users z odpowiednimi argumentami.
        """
        # Arrange - przygotowanie danych testowych
        mock_quiz = Mock()
        mock_user = Mock()
        mock_shared_quiz = Mock()
        mock_shared_quiz.user = mock_user
        mock_shared_quiz.study_group = None
        mock_shared_quiz.quiz = mock_quiz
        self.mock_serializer.save.return_value = mock_shared_quiz

        # Act - wywołanie testowanej metody
        with transaction.atomic():
            self.viewset.perform_create(self.mock_serializer)

        # Assert - sprawdzenie czy powiadomienie zostało wysłane do użytkownika
        mock_notify_users.assert_called_once_with(mock_quiz, mock_user)
        mock_notify_groups.assert_not_called()

    @patch("quizzes.views.notify_quiz_shared_to_users")
    @patch("quizzes.views.notify_quiz_shared_to_groups")
    def test_notification_sent_to_group_when_study_group_exists(self, mock_notify_groups, mock_notify_users):
        """
        Test 2: Powiadomienie wysyłane do grupy

        Sprawdza czy gdy shared_quiz ma przypisaną grupę (study_group),
        ale NIE ma użytkownika, wywołana zostanie funkcja notify_quiz_shared_to_groups.
        """
        # Arrange
        mock_quiz = Mock()
        mock_study_group = Mock()
        mock_shared_quiz = Mock()
        mock_shared_quiz.user = None  # Brak użytkownika
        mock_shared_quiz.study_group = mock_study_group
        mock_shared_quiz.quiz = mock_quiz
        self.mock_serializer.save.return_value = mock_shared_quiz

        # Act
        with transaction.atomic():
            self.viewset.perform_create(self.mock_serializer)

        # Assert
        mock_notify_groups.assert_called_once_with(mock_quiz, mock_study_group)
        mock_notify_users.assert_not_called()

    @patch("quizzes.views.notify_quiz_shared_to_users")
    @patch("quizzes.views.notify_quiz_shared_to_groups")
    def test_user_notification_takes_priority_over_group(self, mock_notify_groups, mock_notify_users):
        """
        Test 3: Priorytet użytkownika nad grupą

        Sprawdza czy gdy shared_quiz ma zarówno użytkownika jak i grupę,
        powiadomienie zostanie wysłane tylko do użytkownika (elif nigdy nie wykona się).
        """
        # Arrange
        mock_quiz = Mock()
        mock_user = Mock()
        mock_study_group = Mock()
        mock_shared_quiz = Mock()
        mock_shared_quiz.user = mock_user
        mock_shared_quiz.study_group = mock_study_group  # Oba ustawione
        mock_shared_quiz.quiz = mock_quiz
        self.mock_serializer.save.return_value = mock_shared_quiz

        # Act
        with transaction.atomic():
            self.viewset.perform_create(self.mock_serializer)

        # Assert - tylko user notification
        mock_notify_users.assert_called_once_with(mock_quiz, mock_user)
        mock_notify_groups.assert_not_called()

    @patch("quizzes.views.notify_quiz_shared_to_users")
    @patch("quizzes.views.notify_quiz_shared_to_groups")
    def test_no_notification_when_no_user_and_no_group(self, mock_notify_groups, mock_notify_users):
        """
        Test 4: Brak powiadomienia gdy brak użytkownika i grupy

        Sprawdza czy gdy shared_quiz nie ma ani użytkownika ani grupy,
        żadne powiadomienie nie zostanie wysłane.
        """
        # Arrange
        mock_shared_quiz = Mock()
        mock_shared_quiz.user = None
        mock_shared_quiz.study_group = None
        self.mock_serializer.save.return_value = mock_shared_quiz

        # Act
        with transaction.atomic():
            self.viewset.perform_create(self.mock_serializer)

        # Assert
        mock_notify_users.assert_not_called()
        mock_notify_groups.assert_not_called()

    @patch("quizzes.views.notify_quiz_shared_to_users")
    @patch("quizzes.views.notify_quiz_shared_to_groups")
    def test_notification_not_called_on_transaction_rollback(self, mock_notify_groups, mock_notify_users):
        """
        Test 5: Brak powiadomienia przy rollback transakcji

        Sprawdza czy gdy transakcja zostanie wycofana (rollback),
        funkcja on_commit nie zostanie wykonana - powiadomienie nie zostanie wysłane.
        To jest kluczowa funkcjonalność transaction.on_commit.
        """
        # Arrange
        mock_quiz = Mock()
        mock_user = Mock()
        mock_shared_quiz = Mock()
        mock_shared_quiz.user = mock_user
        mock_shared_quiz.study_group = None
        mock_shared_quiz.quiz = mock_quiz
        self.mock_serializer.save.return_value = mock_shared_quiz

        # Act - symulacja rollback przez podniesienie wyjątku
        try:
            with transaction.atomic():
                self.viewset.perform_create(self.mock_serializer)
                raise ValueError("Simulated error causing rollback")
        except ValueError:
            pass

        # Assert - powiadomienie nie powinno być wywołane
        mock_notify_users.assert_not_called()
        mock_notify_groups.assert_not_called()

    def test_serializer_save_is_called(self):
        """
        Test 6: Sprawdzenie wywołania serializer.save()

        Prosty test sprawdzający czy metoda save() na serializerze
        jest wywoływana dokładnie raz podczas perform_create.
        """
        # Arrange
        mock_shared_quiz = Mock()
        mock_shared_quiz.user = None
        mock_shared_quiz.study_group = None
        self.mock_serializer.save.return_value = mock_shared_quiz

        # Act
        with transaction.atomic():
            self.viewset.perform_create(self.mock_serializer)

        # Assert
        self.mock_serializer.save.assert_called_once()


class ShouldSendNotificationTests(TransactionTestCase):
    """Testy funkcji should_send_notification"""

    def test_returns_true_when_user_has_email(self):
        """Zwraca True gdy użytkownik ma email"""
        user = Mock()
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


class NotifyQuizSharedToUsersTests(TransactionTestCase):
    """Testy funkcji notify_quiz_shared_to_users"""

    @patch("quizzes.services.notifications.send_mail")
    @patch("quizzes.services.notifications.render_to_string")
    def test_sends_email_to_user_with_email(self, mock_render, mock_send_mail):
        """Wysyła email gdy użytkownik ma adres email"""
        # Arrange
        mock_quiz = Mock()
        mock_quiz.title = "Test Quiz"
        mock_user = Mock()
        mock_user.email = "user@example.com"
        mock_render.side_effect = ["text content", "html content"]

        # Act
        notify_quiz_shared_to_users(mock_quiz, mock_user)

        # Assert
        mock_send_mail.assert_called_once_with(
            subject='Quiz "Test Quiz" został Ci udostępniony',
            message="text content",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=["user@example.com"],
            html_message="html content",
            fail_silently=True,
        )

    @patch("quizzes.services.notifications.send_mail")
    def test_does_not_send_email_when_user_has_no_email(self, mock_send_mail):
        """Nie wysyła emaila gdy użytkownik nie ma adresu email"""
        # Arrange
        mock_quiz = Mock()
        mock_user = Mock()
        mock_user.email = ""

        # Act
        notify_quiz_shared_to_users(mock_quiz, mock_user)

        # Assert
        mock_send_mail.assert_not_called()

    @patch("quizzes.services.notifications.render_to_string")
    @patch("quizzes.services.notifications.send_mail")
    def test_renders_both_templates(self, mock_render):
        """Renderuje zarówno szablon tekstowy jak i HTML"""
        # Arrange
        mock_quiz = Mock()
        mock_quiz.title = "Test Quiz"
        mock_user = Mock()
        mock_user.email = "user@example.com"
        mock_render.side_effect = ["text", "html"]

        # Act
        notify_quiz_shared_to_users(mock_quiz, mock_user)

        # Assert
        self.assertEqual(mock_render.call_count, 2)
        mock_render.assert_any_call(
            "emails/quiz_shared.txt",
            {
                "user": mock_user,
                "quiz": mock_quiz,
            },
        )
        mock_render.assert_any_call(
            "emails/quiz_shared.html",
            {
                "user": mock_user,
                "quiz": mock_quiz,
            },
        )


class NotifyQuizSharedToGroupsTests(TransactionTestCase):
    """Testy funkcji notify_quiz_shared_to_groups"""

    @patch("quizzes.services.notifications.get_connection")
    @patch("quizzes.services.notifications.render_to_string")
    def test_sends_emails_to_all_group_members_with_email(self, mock_render, mock_get_connection):
        """Wysyła emaile do wszystkich członków grupy z adresem email"""
        # Arrange
        mock_quiz = Mock()
        mock_quiz.title = "Test Quiz"

        user1 = Mock()
        user1.email = "user1@example.com"
        user2 = Mock()
        user2.email = "user2@example.com"

        mock_group = Mock()
        mock_group.members.all.return_value = [user1, user2]

        mock_render.side_effect = ["text1", "html1", "text2", "html2"]
        mock_connection = Mock()
        mock_get_connection.return_value = mock_connection

        # Act
        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        # Assert
        mock_connection.send_messages.assert_called_once()
        messages = mock_connection.send_messages.call_args[0][0]
        self.assertEqual(len(messages), 2)

    @patch("quizzes.services.notifications.get_connection")
    def test_does_not_send_when_no_members_have_email(self, mock_get_connection):
        """Nie wysyła emaili gdy żaden członek grupy nie ma adresu email"""
        # Arrange
        mock_quiz = Mock()
        user_without_email = Mock()
        user_without_email.email = ""

        mock_group = Mock()
        mock_group.members.all.return_value = [user_without_email]

        mock_connection = Mock()
        mock_get_connection.return_value = mock_connection

        # Act
        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        # Assert
        mock_connection.send_messages.assert_not_called()

    @patch("quizzes.services.notifications.get_connection")
    def test_does_not_send_when_group_has_no_members(self, mock_get_connection):
        """Nie wysyła emaili gdy grupa nie ma członków"""
        # Arrange
        mock_quiz = Mock()
        mock_group = Mock()
        mock_group.members.all.return_value = []

        mock_connection = Mock()
        mock_get_connection.return_value = mock_connection

        # Act
        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        # Assert
        mock_connection.send_messages.assert_not_called()

    @patch("quizzes.services.notifications.get_connection")
    @patch("quizzes.services.notifications.render_to_string")
    def test_skips_users_without_email(self, mock_render, mock_get_connection):
        """Pomija użytkowników bez adresu email"""
        # Arrange
        mock_quiz = Mock()
        mock_quiz.title = "Test Quiz"

        user_with_email = Mock()
        user_with_email.email = "user@example.com"
        user_without_email = Mock()
        user_without_email.email = ""

        mock_group = Mock()
        mock_group.members.all.return_value = [user_with_email, user_without_email]

        mock_render.side_effect = ["text", "html"]
        mock_connection = Mock()
        mock_get_connection.return_value = mock_connection

        # Act
        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        # Assert
        messages = mock_connection.send_messages.call_args[0][0]
        self.assertEqual(len(messages), 1)

    @patch("quizzes.services.notifications.get_connection")
    @patch("quizzes.services.notifications.render_to_string")
    @patch("quizzes.services.notifications.EmailMultiAlternatives")
    def test_email_has_correct_structure(self, mock_email_class, mock_render, mock_get_connection):
        """Sprawdza poprawną strukturę wiadomości email"""
        # Arrange
        mock_quiz = Mock()
        mock_quiz.title = "Test Quiz"

        mock_user = Mock()
        mock_user.email = "user@example.com"

        mock_group = Mock()
        mock_group.members.all.return_value = [mock_user]

        mock_render.side_effect = ["text content", "html content"]
        mock_email_instance = Mock()
        mock_email_class.return_value = mock_email_instance
        mock_connection = Mock()
        mock_get_connection.return_value = mock_connection

        # Act
        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        # Assert
        mock_email_class.assert_called_once_with(
            subject='Quiz "Test Quiz" został ci udostępniony',
            body="text content",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=["user@example.com"],
        )
        mock_email_instance.attach_alternative.assert_called_once_with("html content", "text/html")

    @patch("quizzes.services.notifications.get_connection")
    @patch("quizzes.services.notifications.render_to_string")
    def test_uses_fail_silently_connection(self, mock_render, mock_get_connection):
        """Używa połączenia z fail_silently=True"""
        # Arrange
        mock_quiz = Mock()
        mock_user = Mock()
        mock_user.email = "user@example.com"
        mock_group = Mock()
        mock_group.members.all.return_value = [mock_user]
        mock_render.side_effect = ["text", "html"]

        # Act
        notify_quiz_shared_to_groups(mock_quiz, mock_group)

        # Assert
        mock_get_connection.assert_called_once_with(fail_silently=True)
