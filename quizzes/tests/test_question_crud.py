from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Answer, Question, Quiz, SharedQuiz, StudyGroup
from users.models import User


class QuestionCRUDTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="test@example.com",
            first_name="Test",
            last_name="Owner",
            student_number="123456",
        )

        self.other_user = User.objects.create(
            email="other@example.com",
            first_name="Other",
            last_name="User",
            student_number="654321",
        )

        self.quiz = Quiz.objects.create(
            title="Test quiz",
            maintainer=self.user,
            visibility=1,
        )

        self.question = Question.objects.create(quiz=self.quiz, order=1, text="Original Question", multiple=False)

        self.answer_1 = Answer.objects.create(
            question=self.question, order=1, text="Original Answer 1", is_correct=True
        )
        self.answer_2 = Answer.objects.create(
            question=self.question, order=2, text="Original Answer 2", is_correct=False
        )

        self.list_url = reverse("question-list")
        self.detail_url = reverse("question-detail", kwargs={"pk": self.question.id})

        self.client.force_authenticate(user=self.user)

    def test_list_questions(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertIn("answers", response.data[0])

    def test_create_question_with_answers(self):
        data = {
            "quiz": self.quiz.id,
            "order": 2,
            "text": "New complicated question?",
            "multiple": True,
            "answers": [
                {"order": 1, "text": "Yes", "is_correct": True},
                {"order": 2, "text": "No", "is_correct": False},
                {"order": 3, "text": "Maybe", "is_correct": True},
            ],
        }
        response = self.client.post(self.list_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Question.objects.count(), 2)

        new_q = Question.objects.get(text="New complicated question?")
        self.assertEqual(new_q.answers.count(), 3)

    def test_create_question_without_answers(self):
        data = {"quiz": self.quiz.id, "order": 3, "text": "Question with no answers", "multiple": False, "answers": []}
        response = self.client.post(self.list_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertTrue(Question.objects.filter(text="Question with no answers").exists())

        new_q = Question.objects.get(text="Question with no answers")
        self.assertEqual(new_q.answers.count(), 0)

    def test_smart_update_answers(self):
        data = {
            "text": "Updated Question Text",
            "answers": [
                {"id": str(self.answer_1.id), "order": 1, "text": "Updated Answer 1", "is_correct": False},
                {"order": 2, "text": "Brand New Answer", "is_correct": True},
            ],
        }

        response = self.client.patch(self.detail_url, data, format="json")

        if response.status_code != status.HTTP_200_OK:
            print(response.data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.question.refresh_from_db()
        self.assertEqual(self.question.text, "Updated Question Text")
        self.assertEqual(self.question.answers.count(), 2)

        updated_a1 = self.question.answers.get(id=self.answer_1.id)
        self.assertEqual(updated_a1.text, "Updated Answer 1")
        self.assertFalse(updated_a1.is_correct)

        self.assertFalse(Answer.objects.filter(id=self.answer_2.id).exists())
        self.assertTrue(self.question.answers.filter(text="Brand New Answer").exists())

    def test_update_security_prevent_moving_quiz(self):
        other_user_quiz = Quiz.objects.create(title="Other", maintainer=self.other_user)

        data = {"quiz": other_user_quiz.id, "text": "Hacked", "answers": []}
        response = self.client.patch(self.detail_url, data, format="json")

        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN])

    def test_access_via_study_group(self):
        group = StudyGroup.objects.create(name="Test Group")
        group.members.add(self.other_user)

        SharedQuiz.objects.create(quiz=self.quiz, study_group=group, allow_edit=True)

        self.client.force_authenticate(user=self.other_user)

        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_distinct_results_for_multi_access(self):
        group = StudyGroup.objects.create(name="Double Access")
        group.members.add(self.other_user)

        SharedQuiz.objects.create(quiz=self.quiz, user=self.other_user, allow_edit=True)
        SharedQuiz.objects.create(quiz=self.quiz, study_group=group, allow_edit=True)

        self.client.force_authenticate(user=self.other_user)

        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_stranger_cannot_see_question(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_read_only_shared_user_cannot_edit(self):
        SharedQuiz.objects.create(quiz=self.quiz, user=self.other_user, allow_edit=False)

        self.client.force_authenticate(user=self.other_user)

        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
