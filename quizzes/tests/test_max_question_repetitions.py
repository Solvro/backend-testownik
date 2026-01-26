import uuid

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import (
    Answer,
    AnswerRecord,
    Question,
    Quiz,
    QuizSession,
)
from users.models import User, UserSettings


class MaxQuestionRepetitionsScenarioATestCase(APITestCase):
    """Testy funkcjonalności max_question_repetitions ze Scenariuszem A (automatyczne pomijanie)."""

    def setUp(self):
        self.user = User.objects.create(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
        )
        # Ustawienia użytkownika z limitem 3
        self.user_settings = UserSettings.objects.create(user=self.user, max_question_repetitions=3)

        self.client.force_authenticate(user=self.user)

        # Quiz i pytania
        self.quiz = Quiz.objects.create(
            title="Test Quiz", description="Quiz testowy", maintainer=self.user, visibility=0
        )

        self.question = Question.objects.create(
            id=uuid.uuid4(), quiz=self.quiz, text="Jaka jest stolica Polski?", order=1, multiple=False
        )

        self.answer_correct = Answer.objects.create(question=self.question, text="Warszawa", is_correct=True, order=1)

        self.answer_wrong1 = Answer.objects.create(question=self.question, text="Kraków", is_correct=False, order=2)

        self.answer_wrong2 = Answer.objects.create(question=self.question, text="Wrocław", is_correct=False, order=3)

        # Drugie pytanie (do sprawdzenia next_question)
        self.question2 = Question.objects.create(
            id=uuid.uuid4(), quiz=self.quiz, text="Ile to 2+2?", order=2, multiple=False
        )

        Answer.objects.create(question=self.question2, text="4", is_correct=True, order=1)

        self.session = QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)

        self.url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.pk})

    def test_answer_below_limit_is_accepted(self):
        """Test: Odpowiedź poniżej limitu jest akceptowana."""
        response = self.client.post(
            self.url,
            {"question_id": str(self.question.id), "selected_answers": [str(self.answer_wrong1.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(AnswerRecord.objects.count(), 1)
        self.assertFalse(AnswerRecord.objects.first().skipped_due_to_limit)

    def test_answer_at_limit_triggers_skip(self):
        """Test: Odpowiedź po osiągnięciu limitu powoduje automatyczne pominięcie."""
        # Wypełnij limit (3 odpowiedzi)
        for _ in range(3):
            self.client.post(
                self.url,
                {"question_id": str(self.question.id), "selected_answers": [str(self.answer_wrong1.id)]},
                format="json",
            )

        # Czwarta próba - powinna zwrócić status skipped (200 OK)
        response = self.client.post(
            self.url,
            {"question_id": str(self.question.id), "selected_answers": [str(self.answer_correct.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)  # ZMIANA: 200 zamiast 400
        self.assertEqual(response.data["status"], "skipped")
        self.assertIn("Wykorzystałeś wszystkie próby", response.data["message"])
        self.assertEqual(response.data["max_question_repetitions"], 3)
        self.assertEqual(response.data["attempts_used"], 3)

        # Sprawdź czy zwrócono następne pytanie
        self.assertIn("next_question", response.data)
        self.assertIsNotNone(response.data["next_question"])
        self.assertEqual(response.data["next_question"]["id"], str(self.question2.id))

    def test_skipped_question_creates_record(self):
        """Test: Pominięcie pytania tworzy rekord z flagą skipped_due_to_limit."""
        # Wypełnij limit
        for _ in range(3):
            self.client.post(
                self.url,
                {"question_id": str(self.question.id), "selected_answers": [str(self.answer_wrong1.id)]},
                format="json",
            )

        # Próba po limicie
        self.client.post(
            self.url,
            {"question_id": str(self.question.id), "selected_answers": [str(self.answer_correct.id)]},
            format="json",
        )

        # Sprawdź rekordy
        skipped_record = AnswerRecord.objects.filter(question=self.question, skipped_due_to_limit=True).first()

        self.assertIsNotNone(skipped_record)
        self.assertEqual(skipped_record.session, self.session)
        self.assertEqual(skipped_record.selected_answers, [])
        self.assertFalse(skipped_record.was_correct)

    def test_multiple_answers_below_limit(self):
        """Test: Wiele odpowiedzi poniżej limitu działa poprawnie."""
        # Odpowiedzi 1, 2, 3
        for answer in [self.answer_wrong1, self.answer_wrong2, self.answer_correct]:
            response = self.client.post(
                self.url, {"question_id": str(self.question.id), "selected_answers": [str(answer.id)]}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(AnswerRecord.objects.filter(skipped_due_to_limit=False).count(), 3)

    def test_limit_zero_disables_restriction(self):
        """Test: Ustawienie limitu na 0 wyłącza ograniczenie."""
        self.user_settings.max_question_repetitions = 0
        self.user_settings.save()

        for i in range(5):
            response = self.client.post(
                self.url,
                {"question_id": str(self.question.id), "selected_answers": [str(self.answer_wrong1.id)]},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(AnswerRecord.objects.count(), 5)

    def test_different_questions_have_separate_counters(self):
        """Test: Różne pytania mają osobne liczniki."""
        # Wyczerp limit dla pierwszego pytania
        for _ in range(3):
            self.client.post(
                self.url,
                {"question_id": str(self.question.id), "selected_answers": [str(self.answer_wrong1.id)]},
                format="json",
            )

        # Pierwsze pytanie jest pomijane
        response = self.client.post(
            self.url,
            {"question_id": str(self.question.id), "selected_answers": [str(self.answer_correct.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "skipped")

        # Drugie pytanie powinno działać normalnie
        response = self.client.post(
            self.url,
            {"question_id": str(self.question2.id), "selected_answers": [str(self.question2.answers.first().id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_session_reset_clears_counter(self):
        """Test: Reset sesji zeruje licznik prób."""
        # Wypełnij limit w pierwszej sesji
        for _ in range(3):
            self.client.post(
                self.url,
                {"question_id": str(self.question.id), "selected_answers": [str(self.answer_wrong1.id)]},
                format="json",
            )

        # Potwierdź, że jest pomijane
        response = self.client.post(
            self.url,
            {"question_id": str(self.question.id), "selected_answers": [str(self.answer_correct.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "skipped")

        # Zresetuj sesję
        delete_url = reverse("quiz-progress", kwargs={"pk": self.quiz.pk})
        self.client.delete(delete_url)

        # W nowej sesji powinno działać (licznik zresetowany)
        response = self.client.post(
            self.url,
            {"question_id": str(self.question.id), "selected_answers": [str(self.answer_correct.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_user_without_settings_has_no_limit(self):
        """Test: User bez UserSettings może odpowiadać bez limitu."""
        user_without_settings = User.objects.create(
            email="nosettings@example.com",
            first_name="No",
            last_name="Settings",
            student_number="999999",
        )
        self.client.force_authenticate(user=user_without_settings)

        # Utwórz nowy quiz dla tego usera
        quiz_for_test = Quiz.objects.create(title="NoSetQuiz", maintainer=user_without_settings, visibility=0)
        q_test = Question.objects.create(id=uuid.uuid4(), quiz=quiz_for_test, text="Q", order=1)
        a_test = Answer.objects.create(question=q_test, text="A", is_correct=False, order=1)

        QuizSession.objects.create(quiz=quiz_for_test, user=user_without_settings, is_active=True)
        url = reverse("quiz-record-answer", kwargs={"pk": quiz_for_test.pk})

        for i in range(10):
            response = self.client.post(
                url, {"question_id": str(q_test.id), "selected_answers": [str(a_test.id)]}, format="json"
            )

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_correct_answer_still_respects_limit(self):
        """Test: Poprawna odpowiedź po osiągnięciu limitu też jest pomijana (jeśli user próbuje ją wysłać)."""
        # 2 błędne + 1 poprawna = 3 próby (limit osiągnięty)
        for _ in range(2):
            self.client.post(
                self.url,
                {"question_id": str(self.question.id), "selected_answers": [str(self.answer_wrong1.id)]},
                format="json",
            )

        self.client.post(
            self.url,
            {"question_id": str(self.question.id), "selected_answers": [str(self.answer_correct.id)]},
            format="json",
        )

        # Kolejna próba
        response = self.client.post(
            self.url,
            {"question_id": str(self.question.id), "selected_answers": [str(self.answer_correct.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "skipped")

    def test_attempt_counter_accuracy(self):
        """Test: Licznik prób jest dokładny (nie liczy rekordów skipped)."""
        # 3 normalne próby
        for _ in range(3):
            self.client.post(
                self.url,
                {"question_id": str(self.question.id), "selected_answers": [str(self.answer_wrong1.id)]},
                format="json",
            )

        # 1 próba "skipująca"
        self.client.post(
            self.url,
            {"question_id": str(self.question.id), "selected_answers": [str(self.answer_wrong1.id)]},
            format="json",
        )

        all_records = AnswerRecord.objects.filter(session=self.session, question=self.question)
        self.assertEqual(all_records.count(), 4)

        attempts_count = all_records.filter(skipped_due_to_limit=False).count()
        self.assertEqual(attempts_count, 3)

        skipped_count = all_records.filter(skipped_due_to_limit=True).count()
        self.assertEqual(skipped_count, 1)
