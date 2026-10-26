import json
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.mcp import QuizTools, StudyTools
from quizzes.models import Answer, OpenMatching, Question, QuestionType, Quiz
from quizzes.services.grading import allowance, matches_open, normalize, osa_distance
from uploads.models import UploadedImage
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

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.data["was_correct"])

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

    def test_tf_has_answer_labels(self):
        self.assertEqual(self.tf_question.answers.count(), 2)
        self.assertFalse(self.tf_question.shuffle_answers)

    def test_open_skipped(self):
        response = self.client.post(
            self.url, {"question_id": str(self.open_question.id), "selected_answers": []}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data["was_correct"])

    def test_open_invalid_value(self):
        for selected in ([12], [True], [None], [{}]):
            with self.subTest(selected=selected):
                response = self.client.post(
                    self.url, {"question_id": str(self.open_question.id), "selected_answers": selected}, format="json"
                )
                self.assertEqual(response.status_code, 400, response.data)

    def test_open_exact_and_similar_with_multiple_accepted_answers(self):
        Answer.objects.create(question=self.open_question, order=2, text="Stolica", is_correct=True)
        for matching, text, correct in [
            ("exact", "Warszwa", False),
            ("similar", "Warszwa", True),
            ("exact", "STOLICA", True),
        ]:
            self.open_question.open_matching = matching
            self.open_question.save()
            response = self.client.post(
                self.url, {"question_id": str(self.open_question.id), "selected_answers": [text]}, format="json"
            )
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data["was_correct"], correct)

    def test_self_assessment_for_every_type(self):
        for question in (self.closed_question, self.multiple_question, self.open_question, self.tf_question):
            for correct in (True, False):
                with self.subTest(type=question.type, correct=correct):
                    response = self.client.post(
                        self.url,
                        {"question_id": str(question.id), "selected_answers": [], "self_assessment": correct},
                        format="json",
                    )
                    self.assertEqual(response.status_code, 201, response.data)
                    self.assertEqual(response.data["was_correct"], correct)
                    self.assertEqual(response.data["selected_answers"], [])
                    self.assertEqual(question.answer_records.latest("answered_at").was_correct, correct)

    def test_self_assessment_rejects_selected_answers(self):
        response = self.client.post(
            self.url,
            {
                "question_id": str(self.closed_question.id),
                "selected_answers": [str(self.correct_answer.id)],
                "self_assessment": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.closed_question.answer_records.exists())

    def test_validation_shared_by_single_bulk_and_mcp(self):
        correct = {"order": 1, "text": "Tak", "is_correct": True}
        wrong = {"order": 2, "text": "Nie", "is_correct": False}
        upload = UploadedImage.objects.create(
            image="uploads/test.png", original_filename="test.png", content_type="image/png", file_size=1
        )
        cases = [
            ("true_false", [correct, wrong, {**wrong, "order": 3}]),
            ("true_false", [correct, {**wrong, "order": 3}]),
            ("true_false", [correct, {**correct, "order": 2}]),
            ("open", [{**correct, "image_url": "https://example.com/a.png"}]),
            ("open", [{**correct, "image_upload": str(upload.id)}]),
            ("open", [correct, wrong]),
            ("open", []),
            ("single_choice", [correct, {**correct, "order": 2}]),
            ("single_choice", [wrong]),
            ("multiple_choice", []),
        ]
        tools = QuizTools(
            request=SimpleNamespace(user=self.user, auth=SimpleNamespace(scope="quizzes:write study:write"))
        )
        for kind, answers in cases:
            payload = {"text": "Walidacja", "type": kind, "answers": answers}
            with self.subTest(type=kind, answers=answers):
                single = self.client.post(
                    reverse("question-list"), {**payload, "quiz": str(self.quiz.id)}, format="json"
                )
                self.assertEqual(single.status_code, 400, single.data)
                bulk = self.client.patch(
                    reverse("quiz-detail", args=[self.quiz.id]), {"questions": [{**payload, "order": 1}]}, format="json"
                )
                self.assertEqual(bulk.status_code, 400, bulk.data)
                self.assertIn("error", tools.add_question(str(self.quiz.id), **payload))

    def test_true_false_shuffling_forced_in_single_and_bulk_writes(self):
        for bulk in (False, True):
            payload = {
                "text": "TF",
                "type": "true_false",
                "shuffle_answers": True,
                "open_matching": "similar",
                "order": 1,
                "answers": [
                    {"order": 1, "text": "Zgadza się", "is_correct": True},
                    {"order": 2, "text": "Nie", "is_correct": False},
                ],
            }
            if bulk:
                response = self.client.patch(
                    reverse("quiz-detail", args=[self.quiz.id]), {"questions": [payload]}, format="json"
                )
                self.assertEqual(response.status_code, 200, response.data)
                question = self.quiz.questions.get()
            else:
                response = self.client.post(
                    reverse("question-list"), {**payload, "quiz": str(self.quiz.id)}, format="json"
                )
                self.assertEqual(response.status_code, 201, response.data)
                question = Question.objects.get(id=response.data["id"])
            self.assertFalse(question.shuffle_answers)
            self.assertEqual(question.open_matching, OpenMatching.SIMILAR)

    def test_partial_edit_keeps_current_type_and_checks_existing_images(self):
        response = self.client.patch(
            reverse("question-detail", args=[self.open_question.id]), {"text": "Nowe"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["type"], "open")
        answer = self.open_question.answers.get()
        answer.image_url = "https://example.com/image.png"
        answer.save()
        response = self.client.patch(
            reverse("question-detail", args=[self.open_question.id]),
            {"answers": [{"id": str(answer.id), "text": "Nowe"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_nested_partial_edit_preserves_type_and_answers(self):
        response = self.client.patch(
            reverse("quiz-detail", args=[self.quiz.id]),
            {"questions": [{"id": str(self.open_question.id), "text": "Nowe", "order": 1}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.open_question.refresh_from_db()
        self.assertEqual(self.open_question.type, "open")
        self.assertEqual(self.open_question.answers.count(), 1)

    def test_new_question_defaults_and_response_fields(self):
        response = self.client.post(
            reverse("question-list"),
            {
                "quiz": str(self.quiz.id),
                "text": "Default",
                "answers": [{"order": 1, "text": "Tak", "is_correct": True}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["type"], "single_choice")
        self.assertTrue(response.data["shuffle_answers"])
        self.assertEqual(response.data["open_matching"], "exact")
        self.assertEqual(
            set(response.data),
            {
                "id",
                "order",
                "text",
                "image_url",
                "image",
                "image_upload",
                "image_width",
                "image_height",
                "explanation",
                "type",
                "shuffle_answers",
                "open_matching",
                "answers",
                "quiz",
                "is_ai_generated",
                "is_markdown_enabled",
            },
        )

    def test_mcp_create_edit_and_submit_open_and_true_false(self):
        request = SimpleNamespace(user=self.user, auth=SimpleNamespace(scope="quizzes:write study:write"))
        quizzes = QuizTools(request=request)
        study = StudyTools(request=request)
        for kind, answers in [
            ("open", [{"text": "Łódź", "is_correct": True}]),
            ("true_false", [{"text": "Prawda", "is_correct": True}, {"text": "Fałsz", "is_correct": False}]),
        ]:
            created = quizzes.add_question(
                str(self.quiz.id), "MCP", answers=answers, type=kind, shuffle_answers=True, open_matching="similar"
            )
            self.assertNotIn("error", created)
            question = Question.objects.get(id=created["id"])
            self.assertEqual(question.type, kind)
            selected = ["Lodz"] if kind == "open" else [str(question.answers.get(is_correct=True).id)]
            self.assertTrue(study.submit_answer(str(self.quiz.id), str(question.id), selected)["was_correct"])
            wrong = ["Krakow"] if kind == "open" else [str(question.answers.get(is_correct=False).id)]
            self.assertFalse(study.submit_answer(str(self.quiz.id), str(question.id), wrong)["was_correct"])
            edited = quizzes.edit_question(str(question.id), text="Zmienione")
            self.assertNotIn("error", edited)
            question.refresh_from_db()
            self.assertEqual(question.type, kind)

    def test_mcp_infers_create_type_and_keeps_edit_type(self):
        tools = QuizTools(
            request=SimpleNamespace(user=self.user, auth=SimpleNamespace(scope="quizzes:write study:write"))
        )
        for answers, kind in [
            ([{"text": "A", "is_correct": True}], "single_choice"),
            ([{"text": "A", "is_correct": False}], "multiple_choice"),
        ]:
            result = tools.add_question(str(self.quiz.id), "Infer", answers=answers)
            self.assertNotIn("error", result)
            question = Question.objects.get(id=result["id"])
            self.assertEqual(question.type, kind)
        result = tools.edit_question(str(self.multiple_question.id), answers=[{"text": "A", "is_correct": True}])
        self.assertNotIn("error", result)
        self.multiple_question.refresh_from_db()
        self.assertEqual(self.multiple_question.type, "multiple_choice")


class GradingVectorsTestCase(SimpleTestCase):
    def test_vectors(self):
        vectors = json.loads(Path(__file__).with_name("grading_vectors.json").read_text())
        for vector in vectors:
            with self.subTest(vector=vector):
                self.assertEqual(matches_open(vector["typed"], [vector["expected"]], vector["mode"]), vector["match"])

    def test_unicode_normalization_and_allowance_boundaries(self):
        self.assertEqual(normalize(" E\u0301\tA\n"), "é a")
        self.assertEqual([allowance(n) for n in (0, 3, 4, 7, 8, 15, 16)], [0, 0, 1, 1, 2, 2, 3])

    def test_osa_is_restricted(self):
        self.assertEqual(osa_distance("CA", "ABC"), 3)
        self.assertEqual(osa_distance("ab", "ba"), 1)
