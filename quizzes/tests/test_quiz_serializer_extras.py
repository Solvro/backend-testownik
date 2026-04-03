from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Question, Quiz, QuizSession
from users.models import User, UserSettings


class QuizSerializerExtrasTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com", password="password", first_name="Test", last_name="User"
        )
        self.settings = UserSettings.objects.create(user=self.user, initial_reoccurrences=3)
        self.quiz = Quiz.objects.create(title="Test Quiz", creator=self.user, folder=self.user.root_folder)
        self.question = Question.objects.create(quiz=self.quiz, order=1, text="Test Question")
        self.url = reverse("quiz-detail", kwargs={"pk": self.quiz.id})

    def test_include_user_settings_only(self):
        """Test response with include=user_settings."""
        QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url, {"include": "user_settings"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("user_settings", response.data)
        self.assertEqual(response.data["user_settings"]["initial_reoccurrences"], 3)
        self.assertNotIn("current_session", response.data)

    def test_include_current_session_only(self):
        """Test response with include=current_session."""
        # Create an active session
        session = QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url, {"include": "current_session"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("user_settings", response.data)
        self.assertIn("current_session", response.data)
        self.assertEqual(str(response.data["current_session"]["id"]), str(session.id))

    def test_include_both(self):
        """Test response with include=user_settings,current_session."""
        QuizSession.objects.create(quiz=self.quiz, user=self.user, is_active=True)
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url, {"include": "user_settings,current_session"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("user_settings", response.data)
        self.assertIn("current_session", response.data)

    def test_include_current_session_no_active_session(self):
        """Test include=current_session when no session exists - should create one."""
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url, {"include": "current_session"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("current_session", response.data)
        # We expect a new session to be created
        self.assertIsNotNone(response.data["current_session"])

    def test_unauthenticated_requests(self):
        """Test that unauthenticated users don't get sensitive data even if requested."""
        self.quiz.visibility = 3
        self.quiz.allow_anonymous = True  # Allow unauthenticated access
        self.quiz.save()

        response = self.client.get(self.url, {"include": "user_settings,current_session"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verify sensitive data is NOT present
        self.assertNotIn("user_settings", response.data)
        self.assertNotIn("current_session", response.data)
