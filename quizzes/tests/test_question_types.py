from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Answer, Question, QuestionType, Quiz
from users.models import User


class QuestionTypesTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="user@test.com", first_name="User", last_name="Test", student_number="123456"
        )
        self.client.force_authenticate(user=self.user)

        self.quiz = Quiz.objects.create(
            title="Test Quiz", creator=self.user, folder=self.user.root_folder, visibility=2
        )

        # Pytanie zamknięte
        self.closed_question = Question.objects.create(
            quiz=self.quiz, order=1, text="Stolica Polski?", question_type=QuestionType.CLOSED
        )
        self.correct_answer = Answer.objects.create(
            question=self.closed_question, order=1, text="Warszawa", is_correct=True
        )
        self.wrong_answer = Answer.objects.create(
            question=self.closed_question, order=2, text="Kraków", is_correct=False
        )

        # Pytanie zamknięte wielokrotnego wyboru
        self.multiple_question = Question.objects.create(
            quiz=self.quiz, order=2, text="Które miasta są w Polsce?", question_type=QuestionType.CLOSED, multiple=True
        )
        self.multiple_correct_1 = Answer.objects.create(
            question=self.multiple_question, order=1, text="Warszawa", is_correct=True
        )
        self.multiple_correct_2 = Answer.objects.create(
            question=self.multiple_question, order=2, text="Kraków", is_correct=True
        )
        self.multiple_wrong = Answer.objects.create(
            question=self.multiple_question, order=3, text="Berlin", is_correct=False
        )

        # Pytanie otwarte
        self.open_question = Question.objects.create(
            quiz=self.quiz, order=3, text="Podaj stolicę Polski", question_type=QuestionType.OPEN
        )
        Answer.objects.create(question=self.open_question, order=1, text="warszawa", is_correct=True)

        # Pytanie prawda/fałsz
        self.tf_question = Question.objects.create(
            quiz=self.quiz, order=4, text="Ziemia jest płaska", question_type=QuestionType.TRUE_FALSE, tf_answer=False
        )

        self.url = reverse("quiz-record-answer", kwargs={"pk": self.quiz.id})

    # -------------------------
    # CLOSED
    # -------------------------

    def test_closed_correct_answer(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.closed_question.id),
                "selected_answers": [str(self.correct_answer.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["was_correct"])

    def test_closed_wrong_answer(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.closed_question.id),
                "selected_answers": [str(self.wrong_answer.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["was_correct"])

    def test_closed_invalid_answer_id(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.closed_question.id),
                "selected_answers": ["00000000-0000-0000-0000-000000000000"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_closed_empty_selected_answers(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.closed_question.id),
                "selected_answers": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_closed_multiple_correct(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.multiple_question.id),
                "selected_answers": [
                    str(self.multiple_correct_1.id),
                    str(self.multiple_correct_2.id),
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["was_correct"])

    def test_closed_multiple_partial_correct(self):
        """Zaznaczenie tylko jednej z dwóch poprawnych odpowiedzi."""
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.multiple_question.id),
                "selected_answers": [str(self.multiple_correct_1.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["was_correct"])

    def test_closed_answer_from_different_question(self):
        """Odpowiedź należąca do innego pytania."""
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.closed_question.id),
                "selected_answers": [str(self.multiple_correct_1.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -------------------------
    # OPEN
    # -------------------------

    def test_open_correct_answer(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.open_question.id),
                "selected_answers": ["Warszawa"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["was_correct"])

    def test_open_correct_answer_with_whitespace(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.open_question.id),
                "selected_answers": ["  Warszawa  "],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["was_correct"])

    def test_open_correct_answer_case_insensitive(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.open_question.id),
                "selected_answers": ["WARSZAWA"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["was_correct"])

    def test_open_wrong_answer(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.open_question.id),
                "selected_answers": ["Kraków"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["was_correct"])

    def test_open_invalid_multiple_answers(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.open_question.id),
                "selected_answers": ["Warszawa", "Kraków"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_open_stores_user_text_in_selected_answers(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.open_question.id),
                "selected_answers": ["Warszawa"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("Warszawa", response.data["selected_answers"])

    def test_open_question_no_correct_answer(self):
        question = Question.objects.create(
            quiz=self.quiz, order=5, text="Pytanie bez odpowiedzi", question_type=QuestionType.OPEN
        )

        response = self.client.post(
            self.url,
            {
                "question_id": str(question.id),
                "selected_answers": ["cokolwiek"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    # -------------------------
    # TRUE/FALSE
    # -------------------------

    def test_tf_correct_answer(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.tf_question.id),
                "selected_answers": [False],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["was_correct"])

    def test_tf_wrong_answer(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.tf_question.id),
                "selected_answers": [True],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["was_correct"])

    def test_tf_invalid_multiple_answers(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.tf_question.id),
                "selected_answers": [True, False],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_tf_missing_tf_answer_on_question(self):
        question = Question.objects.create(
            quiz=self.quiz, order=6, text="Pytanie bez tf_answer", question_type=QuestionType.TRUE_FALSE, tf_answer=None
        )

        response = self.client.post(
            self.url,
            {
                "question_id": str(question.id),
                "selected_answers": [True],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_tf_no_answers_in_database(self):
        """TRUE_FALSE nie powinno tworzyć rekordów Answer."""
        answer_count = Answer.objects.filter(question=self.tf_question).count()
        self.assertEqual(answer_count, 0)
