"""
Tests for the metadata action with API key authentication and visibility-based access control.
"""


from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Answer, Question, Quiz, SharedQuiz
from users.models import User


@override_settings(INTERNAL_API_KEY="test-api-key")
class MetadataActionTestCase(APITestCase):
    """Tests for the metadata action endpoint."""

    def setUp(self):
        self.user = User.objects.create(
            email="maintainer@example.com",
            first_name="Maintainer",
            last_name="User",
            student_number="123456",
        )
        self.other_user = User.objects.create(
            email="other@example.com",
            first_name="Other",
            last_name="User",
            student_number="654321",
        )
        # Create a public quiz with questions (needs 3 answers for preview)
        self.public_quiz = Quiz.objects.create(
            title="Public Quiz",
            maintainer=self.user,
            visibility=3,  # Public
        )
        q1 = Question.objects.create(
            quiz=self.public_quiz,
            order=1,
            text="What is 2+2?",
        )
        Answer.objects.create(question=q1, order=1, text="3", is_correct=False)
        Answer.objects.create(question=q1, order=2, text="4", is_correct=True)
        Answer.objects.create(question=q1, order=3, text="5", is_correct=False)

    def _get_metadata_url(self, quiz_id):
        return reverse("quiz-metadata", kwargs={"pk": quiz_id})

    def test_metadata_requires_api_key(self):
        """Test that metadata endpoint returns 401 without valid API key."""
        url = self._get_metadata_url(self.public_quiz.id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_metadata_invalid_api_key(self):
        """Test that metadata endpoint returns 401 with invalid API key."""
        url = self._get_metadata_url(self.public_quiz.id)
        response = self.client.get(url, HTTP_API_KEY="wrong-key")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_metadata_public_quiz_default_no_preview(self):
        """Test that public quiz returns metadata WITHOUT preview question by default."""
        url = self._get_metadata_url(self.public_quiz.id)
        response = self.client.get(url, HTTP_API_KEY="test-api-key")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Public Quiz")
        self.assertIsNone(response.data.get("preview_question"))

    def test_metadata_public_quiz_with_preview_param(self):
        """Test that public quiz returns preview question when requested."""
        url = self._get_metadata_url(self.public_quiz.id)
        response = self.client.get(f"{url}?include=preview_question", HTTP_API_KEY="test-api-key")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data.get("preview_question"))
        self.assertEqual(response.data["preview_question"]["text"], "What is 2+2?")

    def test_metadata_private_quiz_no_user(self):
        """Test that private quiz returns 403 without user_id."""
        private_quiz = Quiz.objects.create(
            title="Private Quiz",
            maintainer=self.user,
            visibility=0,  # Private
        )
        url = self._get_metadata_url(private_quiz.id)
        response = self.client.get(url, HTTP_API_KEY="test-api-key")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_metadata_private_quiz_maintainer(self):
        """Test that private quiz returns 200 for maintainer."""
        private_quiz = Quiz.objects.create(
            title="Private Quiz",
            maintainer=self.user,
            visibility=0,
        )
        url = self._get_metadata_url(private_quiz.id)

        # Authenticate as maintainer
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            url,
            HTTP_API_KEY="test-api-key",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Private Quiz")

    def test_metadata_shared_quiz_access(self):
        """Test that shared quiz allows access to shared user."""
        shared_quiz = Quiz.objects.create(
            title="Shared Quiz",
            maintainer=self.user,
            visibility=1,  # Shared
        )
        SharedQuiz.objects.create(quiz=shared_quiz, user=self.other_user)

        url = self._get_metadata_url(shared_quiz.id)

        # Access by shared user
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(url, HTTP_API_KEY="test-api-key")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Access by non-shared user
        self.client.logout()
        non_shared_user = User.objects.create(email="rando@example.com")
        self.client.force_authenticate(user=non_shared_user)
        response = self.client.get(url, HTTP_API_KEY="test-api-key")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_metadata_shared_quiz_no_preview(self):
        """Test that shared quiz returns NO preview question even if requested."""
        shared_quiz = Quiz.objects.create(
            title="Shared Quiz",
            maintainer=self.user,
            visibility=1,
        )
        # Create valid question
        q1 = Question.objects.create(quiz=shared_quiz, order=1, text="Shared Q")
        Answer.objects.create(question=q1, order=1, text="A1", is_correct=True)
        Answer.objects.create(question=q1, order=2, text="A2", is_correct=False)
        Answer.objects.create(question=q1, order=3, text="A3", is_correct=False)

        SharedQuiz.objects.create(quiz=shared_quiz, user=self.other_user)

        url = self._get_metadata_url(shared_quiz.id)
        # Access by shared user
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(
            f"{url}?include=preview_question",
            HTTP_API_KEY="test-api-key",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data.get("preview_question"))

    def test_preview_question_criteria_min_answers(self):
        """Test that preview question must have at least 3 answers."""
        quiz = Quiz.objects.create(
            title="Criteria Quiz",
            maintainer=self.user,
            visibility=3,
        )

        # Q1: 2 answers - should be skipped
        q1 = Question.objects.create(quiz=quiz, order=1, text="Q1")
        Answer.objects.create(question=q1, order=1, text="A1")
        Answer.objects.create(question=q1, order=2, text="A2")

        # Q2: 3 answers - should be selected
        q2 = Question.objects.create(quiz=quiz, order=2, text="Q2")
        Answer.objects.create(question=q2, order=1, text="A1")
        Answer.objects.create(question=q2, order=2, text="A2")
        Answer.objects.create(question=q2, order=3, text="A3")

        url = self._get_metadata_url(quiz.id)
        response = self.client.get(f"{url}?include=preview_question", HTTP_API_KEY="test-api-key")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data.get("preview_question"))
        self.assertEqual(response.data["preview_question"]["text"], "Q2")

    def test_preview_question_criteria_no_images(self):
        """Test that preview question must not have images."""
        quiz = Quiz.objects.create(
            title="Image Quiz",
            maintainer=self.user,
            visibility=3,
        )

        # Q1: Image in question
        q1 = Question.objects.create(quiz=quiz, order=1, text="Q1", image_url="http://img.com")
        for i in range(3):
            Answer.objects.create(question=q1, order=i, text="A")

        # Q2: Image in answer
        q2 = Question.objects.create(quiz=quiz, order=2, text="Q2")
        Answer.objects.create(question=q2, order=1, text="A1", image_url="http://img.com")
        Answer.objects.create(question=q2, order=2, text="A2")
        Answer.objects.create(question=q2, order=3, text="A3")

        # Q3: Clean
        q3 = Question.objects.create(quiz=quiz, order=3, text="Q3")
        for i in range(3):
            Answer.objects.create(question=q3, order=i, text="A")

        url = self._get_metadata_url(quiz.id)
        response = self.client.get(f"{url}?include=preview_question", HTTP_API_KEY="test-api-key")

        self.assertIsNotNone(response.data.get("preview_question"))
        self.assertEqual(response.data["preview_question"]["text"], "Q3")
