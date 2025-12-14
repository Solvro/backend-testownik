from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.utils import timezone

from quizzes.models import Quiz, QuizProgress
from users.models import User


class LastUsedQuizzesViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            first_name="Test",
            last_name="User",
            email="test@example.com",
            student_number="123456"
        )
        self.client.force_authenticate(user=self.user)

        # Create a quiz with questions
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            description="Test Description",
            maintainer=self.user,
            visibility=2,
            questions=[
                {
                    "id": "q1",
                    "text": "Question 1",
                    "options": ["A", "B", "C", "D"],
                    "correct": 0
                },
                {
                    "id": "q2",
                    "text": "Question 2",
                    "options": ["A", "B", "C", "D"],
                    "correct": 1
                }
            ]
        )

        # Create quiz progress to make it appear in last used quizzes
        QuizProgress.objects.create(
            quiz=self.quiz,
            user=self.user,
            current_question=0,
            last_activity=timezone.now()
        )

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
