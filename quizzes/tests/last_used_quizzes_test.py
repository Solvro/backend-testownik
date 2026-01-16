from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from quizzes.models import Answer, Question, Quiz, QuizSession
from users.models import User


class LastUsedQuizzesViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            first_name="Test", last_name="User", email="test@example.com", student_number="123456"
        )
        self.client.force_authenticate(user=self.user)

        # Create a quiz
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            description="Test Description",
            maintainer=self.user,
            visibility=2,
        )

        # Create questions with answers
        q1 = Question.objects.create(quiz=self.quiz, order=1, text="Question 1", multiple=False)
        for i, text in enumerate(["A", "B", "C", "D"]):
            Answer.objects.create(question=q1, order=i, text=text, is_correct=(i == 0))

        q2 = Question.objects.create(quiz=self.quiz, order=2, text="Question 2", multiple=False)
        for i, text in enumerate(["A", "B", "C", "D"]):
            Answer.objects.create(question=q2, order=i, text=text, is_correct=(i == 1))

        # Create quiz session to make it appear in last used quizzes
        QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)

    def test_last_used_quizzes_does_not_include_questions(self):
        """Test that the last-used-quizzes endpoint does not return questions"""
        url = reverse("last-used-quizzes")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        # Verify that questions field is NOT in the response
        self.assertNotIn("questions", response.data[0])

        # Verify that other expected fields ARE in the response
        self.assertIn("id", response.data[0])
        self.assertIn("title", response.data[0])
        self.assertIn("description", response.data[0])
        self.assertIn("maintainer", response.data[0])
        self.assertIn("visibility", response.data[0])
        self.assertIn("can_edit", response.data[0])

        # Verify that can_edit is True since user is the maintainer
        self.assertTrue(response.data[0]["can_edit"])
