"""
Tests for Quiz CRUD operations including nested Question and Answer management.
"""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Answer, Question, Quiz
from users.models import User


class QuizCRUDTestCase(APITestCase):
    """Test Quiz Create, Read, Update, Delete operations."""

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
        self.client.force_authenticate(user=self.user)

    # --- CREATE ---
    def test_create_quiz_with_questions(self):
        """Test creating a quiz with nested questions and answers."""
        url = reverse("quiz-list")
        data = {
            "title": "Test Quiz",
            "description": "A test quiz",
            "visibility": 2,
            "questions": [
                {
                    "order": 1,
                    "text": "What is 2+2?",
                    "multiple": False,
                    "answers": [
                        {"order": 1, "text": "3", "is_correct": False},
                        {"order": 2, "text": "4", "is_correct": True},
                    ],
                },
                {
                    "order": 2,
                    "text": "Select all prime numbers",
                    "multiple": True,
                    "answers": [
                        {"order": 1, "text": "2", "is_correct": True},
                        {"order": 2, "text": "3", "is_correct": True},
                        {"order": 3, "text": "4", "is_correct": False},
                    ],
                },
            ],
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify quiz created
        quiz = Quiz.objects.get(id=response.data["id"])
        self.assertEqual(quiz.title, "Test Quiz")
        self.assertEqual(quiz.creator, self.user)

        # Verify questions
        self.assertEqual(quiz.questions.count(), 2)
        q1 = quiz.questions.get(order=1)
        self.assertEqual(q1.text, "What is 2+2?")
        self.assertEqual(q1.answers.count(), 2)
        self.assertTrue(q1.answers.get(order=2).is_correct)

    def test_create_quiz_without_questions(self):
        """Test creating a quiz without questions returns error or empty."""
        url = reverse("quiz-list")
        data = {
            "title": "Empty Quiz",
            "questions": [],
        }
        response = self.client.post(url, data, format="json")
        # Should succeed (empty quiz is allowed)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_quiz_with_explicit_ids(self):
        """
        Test creating a quiz where nested questions and answers contain an 'id' field.
        This provides regression testing for the TypeError fix.
        """
        import uuid

        url = reverse("quiz-list")

        question_id = str(uuid.uuid4())
        answer_id = str(uuid.uuid4())

        data = {
            "title": "Repro Quiz",
            "description": "Testing double id argument",
            "visibility": 2,
            "questions": [
                {
                    "id": question_id,
                    "order": 1,
                    "text": "Question with ID",
                    "multiple": False,
                    "answers": [
                        {"id": answer_id, "order": 1, "text": "Answer with ID", "is_correct": True},
                    ],
                },
            ],
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify created
        quiz = Quiz.objects.get(id=response.data["id"])
        self.assertEqual(quiz.questions.count(), 1)
        self.assertEqual(quiz.questions.first().answers.count(), 1)

    # --- READ ---
    def test_list_own_quizzes(self):
        """Test listing only returns user's own quizzes."""
        Quiz.objects.create(title="My Quiz", creator=self.user, folder=self.user.root_folder)
        Quiz.objects.create(title="Other Quiz", creator=self.other_user, folder=self.other_user.root_folder)

        url = reverse("quiz-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "My Quiz")

    def test_retrieve_quiz_with_questions(self):
        """Test retrieving a single quiz includes nested questions."""
        quiz = Quiz.objects.create(title="My Quiz", creator=self.user, folder=self.user.root_folder)
        q = Question.objects.create(quiz=quiz, order=1, text="Q1")
        Answer.objects.create(question=q, order=1, text="A1", is_correct=True)

        url = reverse("quiz-detail", kwargs={"pk": quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["questions"]), 1)
        self.assertEqual(len(response.data["questions"][0]["answers"]), 1)

    # --- UPDATE ---
    def test_update_quiz_title(self):
        """Test updating quiz title."""
        quiz = Quiz.objects.create(title="Old Title", creator=self.user, folder=self.user.root_folder)
        url = reverse("quiz-detail", kwargs={"pk": quiz.id})

        response = self.client.patch(url, {"title": "New Title"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        quiz.refresh_from_db()
        self.assertEqual(quiz.title, "New Title")

    def test_update_quiz_add_question(self):
        """Test adding a question to an existing quiz."""
        quiz = Quiz.objects.create(title="Quiz", creator=self.user, folder=self.user.root_folder)
        url = reverse("quiz-detail", kwargs={"pk": quiz.id})

        data = {
            "questions": [
                {
                    "order": 1,
                    "text": "New Question",
                    "answers": [{"order": 1, "text": "Answer", "is_correct": True}],
                }
            ]
        }
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(quiz.questions.count(), 1)

    def test_update_quiz_modify_existing_question(self):
        """Test modifying an existing question."""
        quiz = Quiz.objects.create(title="Quiz", creator=self.user, folder=self.user.root_folder)
        question = Question.objects.create(quiz=quiz, order=1, text="Old Text")

        url = reverse("quiz-detail", kwargs={"pk": quiz.id})
        data = {"questions": [{"id": str(question.id), "order": 1, "text": "Updated Text", "answers": []}]}
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        question.refresh_from_db()
        self.assertEqual(question.text, "Updated Text")

    # --- DELETE ---
    def test_delete_quiz(self):
        """Test deleting a quiz."""
        quiz = Quiz.objects.create(title="To Delete", creator=self.user, folder=self.user.root_folder)
        url = reverse("quiz-detail", kwargs={"pk": quiz.id})

        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Quiz.objects.filter(id=quiz.id).exists())

    def test_cannot_delete_other_users_quiz(self):
        """Test that user cannot delete another user's quiz."""
        quiz = Quiz.objects.create(title="Other's Quiz", creator=self.other_user, folder=self.other_user.root_folder)
        url = reverse("quiz-detail", kwargs={"pk": quiz.id})

        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- PERMISSIONS ---
    def test_unauthenticated_cannot_create(self):
        """Test that unauthenticated users cannot create quizzes."""
        self.client.force_authenticate(user=None)
        url = reverse("quiz-list")
        response = self.client.post(url, {"title": "Test", "questions": []}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_quiz_lands_in_root_folder(self):
        """Quiz created via API is assigned to creator's root folder."""
        url = reverse("quiz-list")
        data = {"title": "Auto Folder Quiz", "questions": []}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        quiz = Quiz.objects.get(id=response.data["id"])
        self.assertEqual(quiz.folder_id, self.user.root_folder_id)

    def test_quiz_response_includes_folder(self):
        """GET /quizzes/{id}/ response contains folder field."""
        quiz = Quiz.objects.create(title="Folder Quiz", creator=self.user, folder=self.user.root_folder)
        url = reverse("quiz-detail", kwargs={"pk": quiz.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("folder", response.data)
        self.assertEqual(str(response.data["folder"]), str(self.user.root_folder_id))


class QuizQuestionAnswerTestCase(APITestCase):
    """Comprehensive tests for question and answer management."""

    def setUp(self):
        self.user = User.objects.create(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
        )
        self.client.force_authenticate(user=self.user)
        self.quiz = Quiz.objects.create(title="Test Quiz", creator=self.user, folder=self.user.root_folder)

    # --- ANSWER CORRECTNESS ---
    def test_change_answer_correctness(self):
        """Test changing an answer's is_correct flag."""
        q = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        a = Answer.objects.create(question=q, order=1, text="A1", is_correct=False)

        url = reverse("quiz-detail", kwargs={"pk": self.quiz.id})
        data = {
            "questions": [
                {
                    "id": str(q.id),
                    "order": 1,
                    "text": "Q1",
                    "answers": [{"id": str(a.id), "order": 1, "text": "A1", "is_correct": True}],
                }
            ]
        }
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        a.refresh_from_db()
        self.assertTrue(a.is_correct)

    def test_change_question_multiple_flag(self):
        """Test changing a question's multiple flag."""
        q = Question.objects.create(quiz=self.quiz, order=1, text="Q1", multiple=False)
        a = Answer.objects.create(question=q, order=1, text="A1", is_correct=True)

        url = reverse("quiz-detail", kwargs={"pk": self.quiz.id})
        data = {
            "questions": [
                {
                    "id": str(q.id),
                    "order": 1,
                    "text": "Q1",
                    "multiple": True,
                    "answers": [{"id": str(a.id), "order": 1, "text": "A1", "is_correct": True}],
                }
            ]
        }
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        q.refresh_from_db()
        self.assertTrue(q.multiple)

    # --- ADD/REMOVE ANSWERS ---
    def test_add_answer_to_existing_question(self):
        """Test adding a new answer to an existing question."""
        q = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        a1 = Answer.objects.create(question=q, order=1, text="A1", is_correct=True)

        url = reverse("quiz-detail", kwargs={"pk": self.quiz.id})
        data = {
            "questions": [
                {
                    "id": str(q.id),
                    "order": 1,
                    "text": "Q1",
                    "answers": [
                        {"id": str(a1.id), "order": 1, "text": "A1", "is_correct": True},
                        {"order": 2, "text": "A2 New", "is_correct": False},
                    ],
                }
            ]
        }
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(q.answers.count(), 2)

    def test_remove_answer_from_question(self):
        """Test removing an answer (by omitting it from the list)."""
        q = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        a1 = Answer.objects.create(question=q, order=1, text="A1", is_correct=True)
        a2 = Answer.objects.create(question=q, order=2, text="A2", is_correct=False)

        url = reverse("quiz-detail", kwargs={"pk": self.quiz.id})
        data = {
            "questions": [
                {
                    "id": str(q.id),
                    "order": 1,
                    "text": "Q1",
                    "answers": [{"id": str(a1.id), "order": 1, "text": "A1", "is_correct": True}],
                }
            ]
        }
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # a2 should be deleted
        self.assertFalse(Answer.objects.filter(id=a2.id).exists())
        self.assertEqual(q.answers.count(), 1)

    def test_remove_question_from_quiz(self):
        """Test removing a question (by omitting it from the list)."""
        q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        q2 = Question.objects.create(quiz=self.quiz, order=2, text="Q2")

        url = reverse("quiz-detail", kwargs={"pk": self.quiz.id})
        data = {"questions": [{"id": str(q1.id), "order": 1, "text": "Q1", "answers": []}]}
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # q2 should be deleted
        self.assertFalse(Question.objects.filter(id=q2.id).exists())
        self.assertEqual(self.quiz.questions.count(), 1)

    # --- UUID HANDLING ---
    def test_providing_new_uuid_creates_new_object(self):
        """Test that providing a new UUID creates a new question."""
        import uuid

        new_uuid = str(uuid.uuid4())
        url = reverse("quiz-detail", kwargs={"pk": self.quiz.id})
        data = {
            "questions": [
                {
                    "id": new_uuid,
                    "order": 1,
                    "text": "New Question",
                    "answers": [{"order": 1, "text": "A1", "is_correct": True}],
                }
            ]
        }
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # A question should exist (either with new UUID or auto-generated)
        self.assertEqual(self.quiz.questions.count(), 1)

    # --- EDGE CASES ---
    def test_update_question_text(self):
        """Test updating only the question text."""
        q = Question.objects.create(quiz=self.quiz, order=1, text="Old Text")

        url = reverse("quiz-detail", kwargs={"pk": self.quiz.id})
        data = {"questions": [{"id": str(q.id), "order": 1, "text": "New Text", "answers": []}]}
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        q.refresh_from_db()
        self.assertEqual(q.text, "New Text")

    def test_reorder_questions(self):
        """Test reordering questions."""
        q1 = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        q2 = Question.objects.create(quiz=self.quiz, order=2, text="Q2")

        url = reverse("quiz-detail", kwargs={"pk": self.quiz.id})
        data = {
            "questions": [
                {"id": str(q2.id), "order": 1, "text": "Q2", "answers": []},
                {"id": str(q1.id), "order": 2, "text": "Q1", "answers": []},
            ]
        }
        response = self.client.patch(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        q1.refresh_from_db()
        q2.refresh_from_db()
        self.assertEqual(q1.order, 2)
        self.assertEqual(q2.order, 1)
