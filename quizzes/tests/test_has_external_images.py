"""Tests for has_external_images serializer field in QuizSerializer."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from quizzes.models import Answer, Question, Quiz
from quizzes.serializers import QuizSerializer
from uploads.models import UploadedImage
from users.models import User


class HasExternalImagesTests(TestCase):
    """
    Unit tests for the has_external_images field in QuizSerializer.

    Verifies that the field correctly identifies when a quiz contains
    external image URLs (not uploaded images).
    """

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com", password="password", first_name="Test", last_name="User"
        )
        self.quiz = Quiz.objects.create(title="Test Quiz", maintainer=self.user)

        # Create a dummy uploaded image
        self.uploaded_image = UploadedImage.objects.create(
            image=SimpleUploadedFile("test.jpg", b"content", content_type="image/jpeg"),
            original_filename="test.jpg",
            file_size=100,
            uploaded_by=self.user,
        )

    def test_no_images(self):
        """Quiz with no images should return has_external_images=False."""
        Question.objects.create(quiz=self.quiz, order=1, text="Test Question")
        serializer = QuizSerializer(self.quiz)
        self.assertFalse(serializer.data["has_external_images"])

    def test_question_with_external_image(self):
        """Quiz with external image URL in question should return True."""
        Question.objects.create(
            quiz=self.quiz,
            order=1,
            text="Test Question",
            image_url="https://example.com/image.jpg",
        )
        serializer = QuizSerializer(self.quiz)
        self.assertTrue(serializer.data["has_external_images"])

    def test_question_with_empty_image_url(self):
        """Quiz with empty image_url should return False."""
        Question.objects.create(
            quiz=self.quiz,
            order=1,
            text="Test Question",
            image_url="",
        )
        serializer = QuizSerializer(self.quiz)
        self.assertFalse(serializer.data["has_external_images"])

    def test_question_with_uploaded_image_and_url(self):
        """
        Quiz with both image_url and image_upload should return False.
        Uploaded image takes precedence, so the URL is ignored/considered internal/overridden.
        """
        Question.objects.create(
            quiz=self.quiz,
            order=1,
            text="Test Question",
            image_url="https://example.com/image.jpg",
            image_upload=self.uploaded_image,
        )
        serializer = QuizSerializer(self.quiz)
        self.assertFalse(serializer.data["has_external_images"])

    def test_answer_with_external_image(self):
        """Quiz with external image URL in answer should return True."""
        question = Question.objects.create(quiz=self.quiz, order=1, text="Test Question")
        Answer.objects.create(
            question=question,
            order=1,
            text="Test Answer",
            image_url="https://example.com/image.jpg",
        )
        serializer = QuizSerializer(self.quiz)
        self.assertTrue(serializer.data["has_external_images"])

    def test_answer_with_empty_image_url(self):
        """Quiz with empty image_url in answer should return False."""
        question = Question.objects.create(quiz=self.quiz, order=1, text="Test Question")
        Answer.objects.create(
            question=question,
            order=1,
            text="Test Answer",
            image_url="",
        )
        serializer = QuizSerializer(self.quiz)
        self.assertFalse(serializer.data["has_external_images"])

    def test_answer_with_uploaded_image_and_url(self):
        """
        Answer with both image_url and image_upload should return False.
        Uploaded image takes precedence.
        """
        question = Question.objects.create(quiz=self.quiz, order=1, text="Test Question")
        Answer.objects.create(
            question=question,
            order=1,
            text="Test Answer",
            image_url="https://example.com/image.jpg",
            image_upload=self.uploaded_image,
        )
        serializer = QuizSerializer(self.quiz)
        self.assertFalse(serializer.data["has_external_images"])

    def test_mixed_scenario(self):
        """
        Complex scenario:
        - Q1: Uploaded image (False)
        - Q2: External image (True) -> Makes whole quiz True
        - Q3: No image (False)
        """
        # Q1: Uploaded
        Question.objects.create(
            quiz=self.quiz, order=1, text="Q1", image_url="http://ignore.com", image_upload=self.uploaded_image
        )

        # Q2: External
        Question.objects.create(quiz=self.quiz, order=2, text="Q2", image_url="https://example.com/real_external.jpg")

        # Q3: None
        Question.objects.create(quiz=self.quiz, order=3, text="Q3")

        serializer = QuizSerializer(self.quiz)
        self.assertTrue(serializer.data["has_external_images"])

    def test_image_url_null(self):
        """Quiz with null image_url should return False."""
        Question.objects.create(
            quiz=self.quiz,
            order=1,
            text="Test Question",
            image_url=None,
        )
        serializer = QuizSerializer(self.quiz)
        self.assertFalse(serializer.data["has_external_images"])
