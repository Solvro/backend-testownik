from types import SimpleNamespace

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.mcp import QuizTools, StudyTools
from quizzes.models import Answer, OpenMatching, Question, QuestionType, Quiz
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
            quiz=self.quiz, order=1, text="Stolica Polski?", type=QuestionType.SINGLE_CHOICE
        )
        self.correct_answer = Answer.objects.create(
            question=self.closed_question, order=1, text="Warszawa", is_correct=True
        )
        self.wrong_answer = Answer.objects.create(
            question=self.closed_question, order=2, text="Kraków", is_correct=False
        )

        # Pytanie zamknięte wielokrotnego wyboru
        self.multiple_question = Question.objects.create(
            quiz=self.quiz, order=2, text="Które miasta są w Polsce?", type=QuestionType.MULTIPLE_CHOICE
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
            quiz=self.quiz, order=3, text="Podaj stolicę Polski", type=QuestionType.OPEN
        )
        Answer.objects.create(question=self.open_question, order=1, text="warszawa", is_correct=True)

        # Pytanie prawda/fałsz
        self.tf_question = Question.objects.create(
            quiz=self.quiz, order=4, text="Ziemia jest płaska", type=QuestionType.TRUE_FALSE
        )
        self.tf_true = Answer.objects.create(question=self.tf_question, order=1, text="Prawda", is_correct=False)
        self.tf_false = Answer.objects.create(question=self.tf_question, order=2, text="Fałsz", is_correct=True)

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

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

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
            quiz=self.quiz, order=5, text="Pytanie bez odpowiedzi", type=QuestionType.OPEN
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
                "selected_answers": [str(self.tf_false.id)],
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
                "selected_answers": [str(self.tf_true.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["was_correct"])

    def test_tf_both_answers_are_wrong(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.tf_question.id),
                "selected_answers": [str(self.tf_true.id), str(self.tf_false.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["was_correct"])

    def test_tf_rejects_boolean_answers(self):
        """True/false answers are answer rows, so booleans are not answer IDs."""
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.tf_question.id),
                "selected_answers": [False],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_open_skip_is_incorrect(self):
        response = self.client.post(
            self.url,
            {"question_id": str(self.open_question.id), "selected_answers": []},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["was_correct"])

    def test_open_accepts_any_accepted_answer(self):
        Answer.objects.create(question=self.open_question, order=2, text="Stolica", is_correct=True)
        response = self.client.post(
            self.url,
            {"question_id": str(self.open_question.id), "selected_answers": ["stolica"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["was_correct"])

    # -------------------------
    # MCP
    # -------------------------

    def mcp_tools(self):
        request = SimpleNamespace(user=self.user, auth=SimpleNamespace(scope="quizzes:write study:write"))
        return QuizTools(request=request), StudyTools(request=request)

    def test_mcp_creates_edits_and_answers_every_type(self):
        quizzes, study = self.mcp_tools()
        cases = [
            ("single_choice", [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}], "A"),
            ("multiple_choice", [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": True}], None),
            ("true_false", [{"text": "Prawda", "is_correct": False}, {"text": "Fałsz", "is_correct": True}], "Fałsz"),
            ("open", [{"text": "Łódź", "is_correct": True}], None),
        ]
        for kind, answers, correct_text in cases:
            with self.subTest(type=kind):
                created = quizzes.add_question(str(self.quiz.id), "MCP", answers=answers, type=kind)
                self.assertNotIn("error", created)
                question = Question.objects.get(id=created["id"])
                self.assertEqual(question.type, kind)
                self.assertEqual(question.open_matching, OpenMatching.EXACT)
                if kind == "open":
                    right, wrong = [" łódź "], ["Kraków"]
                elif kind == "multiple_choice":
                    right = [str(answer.id) for answer in question.answers.all()]
                    wrong = right[:1]
                else:
                    right = [str(question.answers.get(text=correct_text).id)]
                    wrong = [str(question.answers.exclude(text=correct_text).get().id)]
                self.assertTrue(study.submit_answer(str(self.quiz.id), str(question.id), right)["was_correct"])
                self.assertFalse(study.submit_answer(str(self.quiz.id), str(question.id), wrong)["was_correct"])
                self.assertNotIn("error", quizzes.edit_question(str(question.id), text="Zmienione"))
                question.refresh_from_db()
                self.assertEqual(question.type, kind)

    def test_mcp_stores_open_matching(self):
        quizzes, _ = self.mcp_tools()
        created = quizzes.add_question(
            str(self.quiz.id),
            "MCP",
            answers=[{"text": "Łódź", "is_correct": True}],
            type="open",
            open_matching="similar",
        )
        self.assertNotIn("error", created)
        self.assertEqual(Question.objects.get(id=created["id"]).open_matching, OpenMatching.SIMILAR)

    def test_mcp_infers_create_type_and_keeps_edit_type(self):
        quizzes, _ = self.mcp_tools()
        for answers, kind in [
            ([{"text": "A", "is_correct": True}], "single_choice"),
            ([{"text": "A", "is_correct": True}, {"text": "B", "is_correct": True}], "multiple_choice"),
        ]:
            result = quizzes.add_question(str(self.quiz.id), "Infer", answers=answers)
            self.assertNotIn("error", result)
            self.assertEqual(Question.objects.get(id=result["id"]).type, kind)
        result = quizzes.edit_question(str(self.multiple_question.id), answers=[{"text": "A", "is_correct": True}])
        self.assertNotIn("error", result)
        self.multiple_question.refresh_from_db()
        self.assertEqual(self.multiple_question.type, QuestionType.MULTIPLE_CHOICE)

    def test_mcp_rejects_answers_that_do_not_fit_the_type(self):
        quizzes, _ = self.mcp_tools()
        correct = {"text": "A", "is_correct": True}
        wrong = {"text": "B", "is_correct": False}
        cases = [
            ("true_false", [correct]),
            ("true_false", [correct, {**correct, "text": "C"}]),
            ("open", [correct, wrong]),
            ("open", [{**correct, "image_url": "https://example.com/a.png"}]),
            ("open", []),
            ("single_choice", [correct, {**correct, "text": "C"}]),
            ("single_choice", [wrong]),
            ("multiple_choice", []),
        ]
        for kind, answers in cases:
            with self.subTest(type=kind, answers=answers):
                self.assertIn("error", quizzes.add_question(str(self.quiz.id), "Walidacja", answers=answers, type=kind))
                self.assertIn(
                    "error", quizzes.add_questions(str(self.quiz.id), [{"text": "W", "type": kind, "answers": answers}])
                )
        self.assertEqual(self.quiz.questions.count(), 4)

    def test_mcp_type_changes_check_the_final_answers(self):
        quizzes, _ = self.mcp_tools()
        self.assertIn("error", quizzes.edit_question(str(self.multiple_question.id), type="single_choice"))
        self.assertIn(
            "error", quizzes.edit_questions([{"question_id": str(self.multiple_question.id), "type": "single_choice"}])
        )
        self.multiple_question.refresh_from_db()
        self.assertEqual(self.multiple_question.type, QuestionType.MULTIPLE_CHOICE)
        result = quizzes.edit_question(
            str(self.multiple_question.id), type="open", answers=[{"text": "Warszawa", "is_correct": True}]
        )
        self.assertNotIn("error", result)
        self.multiple_question.refresh_from_db()
        self.assertEqual(self.multiple_question.type, QuestionType.OPEN)

    def test_mcp_conversion_to_open_checks_kept_answer_images(self):
        quizzes, _ = self.mcp_tools()
        self.correct_answer.image_url = "https://example.com/warszawa.png"
        self.correct_answer.save()
        answers = [{"id": str(self.correct_answer.id), "text": "Warszawa", "is_correct": True}]
        self.assertIn("error", quizzes.edit_question(str(self.closed_question.id), type="open", answers=answers))
        self.assertIn(
            "error",
            quizzes.edit_questions([{"question_id": str(self.closed_question.id), "type": "open", "answers": answers}]),
        )
        self.closed_question.refresh_from_db()
        self.assertEqual(self.closed_question.type, QuestionType.SINGLE_CHOICE)

    def test_mcp_multiple_choice_needs_a_correct_answer(self):
        quizzes, _ = self.mcp_tools()
        wrong = [{"text": "Zła", "is_correct": False}]
        self.assertIn("error", quizzes.add_question(str(self.quiz.id), "Brak", answers=wrong, type="multiple_choice"))
        self.assertIn("error", quizzes.add_question(str(self.quiz.id), "Brak", answers=wrong))
        self.assertIn("error", quizzes.edit_question(str(self.multiple_question.id), answers=wrong))
        self.multiple_question.answers.update(is_correct=False)
        self.assertIn("error", quizzes.edit_question(str(self.multiple_question.id), type="multiple_choice"))
        self.assertEqual(self.quiz.questions.count(), 4)
