from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase, TransactionTestCase
from django.db import transaction
from quizzes.views import SharedQuizViewSet


class SharedQuizViewSetPerformCreateTests(TransactionTestCase):

    def setUp(self):
        self.viewset = SharedQuizViewSet()
        self.mock_serializer = Mock()

    @patch('quizzes.views.notify_quiz_shared_to_users')
    @patch('quizzes.views.notify_quiz_shared_to_groups')
    def test_notification_sent_to_user_when_user_exists(
            self, mock_notify_groups, mock_notify_users
    ):
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

    @patch('quizzes.views.notify_quiz_shared_to_users')
    @patch('quizzes.views.notify_quiz_shared_to_groups')
    def test_notification_sent_to_group_when_study_group_exists(
            self, mock_notify_groups, mock_notify_users
    ):
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

    @patch('quizzes.views.notify_quiz_shared_to_users')
    @patch('quizzes.views.notify_quiz_shared_to_groups')
    def test_user_notification_takes_priority_over_group(
            self, mock_notify_groups, mock_notify_users
    ):
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

    @patch('quizzes.views.notify_quiz_shared_to_users')
    @patch('quizzes.views.notify_quiz_shared_to_groups')
    def test_no_notification_when_no_user_and_no_group(
            self, mock_notify_groups, mock_notify_users
    ):
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

    @patch('quizzes.views.notify_quiz_shared_to_users')
    @patch('quizzes.views.notify_quiz_shared_to_groups')
    def test_notification_not_called_on_transaction_rollback(
            self, mock_notify_groups, mock_notify_users
    ):
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
                raise Exception("Simulated error causing rollback")
        except Exception:
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
