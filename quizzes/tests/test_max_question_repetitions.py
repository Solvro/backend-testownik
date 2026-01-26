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


class MaxQuestionRepetitionsBasicTestCase(APITestCase):
    """Testy podstawowej funkcjonalności max_question_repetitions - blokowanie po limicie."""

    def setUp(self):
        self.user = User.objects.create(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
        )
        self.other_user = User.objects.create(
            email="other@example.com",
            first_name="Other",
            last_name="User",
            student_number="654321",
        )

        # Ustawienia użytkownika z limitem 3
        self.user_settings = UserSettings.objects.create(
            user=self.user,
            max_question_repetitions=3
        )

        self.client.force_authenticate(user=self.user)

        # Quiz i pytania
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            description="Quiz testowy",
            maintainer=self.user,
            visibility=0
        )

        self.question = Question.objects.create(
            id=uuid.uuid4(),
            quiz=self.quiz,
            text="Jaka jest stolica Polski?",
            order=1,
            multiple=False
        )

        self.answer_correct = Answer.objects.create(
            question=self.question,
            text="Warszawa",
            is_correct=True,
            order=1
        )

        self.answer_wrong1 = Answer.objects.create(
            question=self.question,
            text="Kraków",
            is_correct=False,
            order=2
        )

        self.answer_wrong2 = Answer.objects.create(
            question=self.question,
            text="Wrocław",
            is_correct=False,
            order=3
        )

        # Drugie pytanie
        self.question2 = Question.objects.create(
            id=uuid.uuid4(),
            quiz=self.quiz,
            text="Ile to 2+2?",
            order=2,
            multiple=False
        )

        Answer.objects.create(
            question=self.question2,
            text="4",
            is_correct=True,
            order=1
        )

        self.session = QuizSession.objects.create(
            quiz=self.quiz,
            user=self.user,
            is_active=True
        )

        self.url = reverse('quiz-record-answer', kwargs={'pk': self.quiz.pk})

    def test_answer_below_limit_is_accepted(self):
        """Test: Odpowiedź poniżej limitu jest akceptowana."""
        response = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_wrong1.id)]
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(AnswerRecord.objects.count(), 1)
        self.assertIn('question', response.data)

    def test_first_answer_creates_record(self):
        """Test: Pierwsza odpowiedź tworzy rekord w bazie."""
        response = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_correct.id)]
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        record = AnswerRecord.objects.get(question=self.question)
        self.assertEqual(record.session, self.session)
        self.assertTrue(record.was_correct)

    def test_multiple_answers_below_limit(self):
        """Test: Wiele odpowiedzi poniżej limitu działa poprawnie."""
        # Pierwsza odpowiedź
        response1 = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_wrong1.id)]
        }, format='json')
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        # Druga odpowiedź
        response2 = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_wrong2.id)]
        }, format='json')
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)

        # Trzecia odpowiedź (ostatnia dozwolona)
        response3 = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_correct.id)]
        }, format='json')
        self.assertEqual(response3.status_code, status.HTTP_201_CREATED)

        # Sprawdź że wszystkie zostały zapisane
        self.assertEqual(AnswerRecord.objects.count(), 3)

    def test_answer_at_limit_is_blocked(self):
        """Test: Odpowiedź po osiągnięciu limitu jest blokowana."""
        # Wypełnij limit (3 odpowiedzi)
        for i in range(3):
            response = self.client.post(self.url, {
                'question_id': str(self.question.id),
                'selected_answers': [str(self.answer_wrong1.id)]
            }, format='json')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Czwarta próba - powinna być zablokowana
        response = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_correct.id)]
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
        self.assertIn('Przekroczono maksymalną', response.data['error'])

        # Sprawdź że w bazie jest tylko 3 rekordy (czwarty nie został zapisany)
        self.assertEqual(AnswerRecord.objects.count(), 3)

    def test_blocked_response_contains_limit_info(self):
        """Test: Odpowiedź blokująca zawiera informacje o limicie."""

        # Wypełnij limit
        for i in range(3):
            response = self.client.post(self.url, {
                'question_id': str(self.question.id),
                'selected_answers': [str(self.answer_wrong1.id)]
            }, format='json')

            self.assertEqual(
                response.status_code,
                status.HTTP_201_CREATED,
                f"Odpowiedź {i + 1}/3 powinna być zaakceptowana"
            )

        # Próba po limicie
        blocked_response = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_correct.id)]
        }, format='json')

        self.assertEqual(
            blocked_response.status_code,
            status.HTTP_400_BAD_REQUEST,
            "Czwarta odpowiedź powinna być zablokowana"
        )

        self.assertIn('error', blocked_response.data)
        self.assertIn('max_question_repetitions', blocked_response.data)
        self.assertEqual(blocked_response.data['max_question_repetitions'], 3)
        self.assertEqual(blocked_response.data['attempts_used'], 3)
        self.assertEqual(blocked_response.data['remaining_attempts'], 0)

    def test_limit_zero_disables_restriction(self):
        """Test: Ustawienie limitu na 0 wyłącza ograniczenie."""
        self.user_settings.max_question_repetitions = 0
        self.user_settings.save()

        # Spróbuj odpowiedzieć więcej niż 3 razy
        for i in range(5):
            response = self.client.post(self.url, {
                'question_id': str(self.question.id),
                'selected_answers': [str(self.answer_wrong1.id)]
            }, format='json')

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Wszystkie powinny zostać zapisane
        self.assertEqual(AnswerRecord.objects.count(), 5)


    def test_different_questions_have_separate_counters(self):
        """Test: Różne pytania mają osobne liczniki."""
        # 3 odpowiedzi na pierwsze pytanie (wyczerpanie limitu)
        for _ in range(3):
            self.client.post(self.url, {
                'question_id': str(self.question.id),
                'selected_answers': [str(self.answer_wrong1.id)]
            }, format='json')

        # Pierwsze pytanie jest zablokowane
        response = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_correct.id)]
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Ale drugie pytanie powinno działać
        response = self.client.post(self.url, {
            'question_id': str(self.question2.id),
            'selected_answers': [str(self.question2.answers.first().id)]
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_session_reset_clears_counter(self):
        """Test: Reset sesji zeruje licznik prób."""
        # Wypełnij limit w pierwszej sesji
        for _ in range(3):
            self.client.post(self.url, {
                'question_id': str(self.question.id),
                'selected_answers': [str(self.answer_wrong1.id)]
            }, format='json')

        # Pytanie jest zablokowane
        response = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_correct.id)]
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Zresetuj sesję
        delete_url = reverse('quiz-progress', kwargs={'pk': self.quiz.pk})
        self.client.delete(delete_url)

        # W nowej sesji powinno działać
        response = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_correct.id)]
        }, format='json')
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

        quiz_for_test = Quiz.objects.create(
            title="Test Quiz No Settings",
            maintainer=user_without_settings,
            visibility=0
        )

        question_for_test = Question.objects.create(
            id=uuid.uuid4(),
            quiz=quiz_for_test,
            text="Test question",
            order=1,
        )

        answer_for_test = Answer.objects.create(
            question=question_for_test,
            text="Answer",
            is_correct=False,
            order=1
        )

        session = QuizSession.objects.create(
            quiz=quiz_for_test,
            user=user_without_settings,
            is_active=True
        )

        url = reverse('quiz-record-answer', kwargs={'pk': quiz_for_test.pk})

        for i in range(10):
            response = self.client.post(url, {
                'question_id': str(question_for_test.id),
                'selected_answers': [str(answer_for_test.id)]
            }, format='json')

            self.assertEqual(
                response.status_code,
                status.HTTP_201_CREATED,
                f"User bez settings powinien móc odpowiadać bez limitu. Attempt {i + 1} failed."
            )

        self.assertEqual(
            AnswerRecord.objects.filter(session=session).count(),
            10
        )


    def test_correct_answer_still_respects_limit(self):
        """Test: Poprawna odpowiedź też jest liczona do limitu."""
        # 2 błędne odpowiedzi
        for _ in range(2):
            self.client.post(self.url, {
                'question_id': str(self.question.id),
                'selected_answers': [str(self.answer_wrong1.id)]
            }, format='json')

        # 1 poprawna (3-cia, ostatnia)
        response = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_correct.id)]
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Kolejna próba jest zablokowana (mimo że poprzednia była poprawna)
        response = self.client.post(self.url, {
            'question_id': str(self.question.id),
            'selected_answers': [str(self.answer_correct.id)]
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_attempt_counter_accuracy(self):
        """Test: Licznik prób jest dokładny."""
        for i in range(1, 4):
            self.client.post(self.url, {
                'question_id': str(self.question.id),
                'selected_answers': [str(self.answer_wrong1.id)]
            }, format='json')

            count = AnswerRecord.objects.filter(
                session=self.session,
                question=self.question
            ).count()
            self.assertEqual(count, i)
