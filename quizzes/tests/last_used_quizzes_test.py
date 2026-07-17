from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from quizzes.models import Answer, Folder, FolderType, Question, Quiz, QuizSession
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
            creator=self.user,
            folder=self.user.root_folder,
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
        response = self.client.get(url, {"limit": 10})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertEqual(len(response.data["results"]), 1)

        result = response.data["results"][0]

        # Verify that questions field is NOT in the response
        self.assertNotIn("questions", result)

        # Verify that other expected fields ARE in the response
        self.assertIn("id", result)
        self.assertIn("title", result)
        self.assertIn("description", result)
        self.assertIn("creator", result)
        self.assertIn("visibility", result)
        self.assertIn("can_edit", result)

        # Verify that can_edit is True since user is the creator
        self.assertTrue(result["can_edit"])

    def test_last_used_quizzes_includes_archived_and_excludes_deleted_quizzes(self):
        archive_folder = Folder.objects.get(owner=self.user, folder_type=FolderType.ARCHIVE)
        trash_folder = Folder.objects.get(owner=self.user, folder_type=FolderType.TRASH)
        archived_quiz = Quiz.objects.create(title="Archived", creator=self.user, folder=archive_folder, visibility=2)
        deleted_quiz = Quiz.objects.create(title="Deleted", creator=self.user, folder=trash_folder, visibility=2)
        Quiz.objects.filter(id=archived_quiz.id).update(archived_at="2026-01-01T00:00:00Z")
        Quiz.objects.filter(id=deleted_quiz.id).update(deleted_at="2026-01-01T00:00:00Z")
        QuizSession.objects.create(quiz=archived_quiz, user=self.user, is_active=True)
        QuizSession.objects.create(quiz=deleted_quiz, user=self.user, is_active=True)

        response = self.client.get(reverse("last-used-quizzes"), {"limit": 10})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(returned_ids, {str(self.quiz.id), str(archived_quiz.id)})

    def test_pagination(self):
        """Test that pagination works correctly"""
        # Create 5 more sessions to have total 6 items
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        for i in range(5):
            q = Quiz.objects.create(title=f"Quiz {i}", creator=self.user, folder=self.user.root_folder, visibility=2)
            session = QuizSession.objects.create(quiz=q, user=self.user, is_active=True)
            session.started_at = now - timedelta(minutes=5 - i)
            session.save()

        url = reverse("last-used-quizzes")

        # Test default (should be full list or default page size)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Test limit
        response = self.client.get(url, {"limit": 2})
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNotNone(response.data["next"])

        # Test offset
        response = self.client.get(url, {"limit": 2, "offset": 2})
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNotNone(response.data["previous"])


class RandomQuestionViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(
            first_name="Random", last_name="User", email="random@example.com", student_number="654321"
        )
        self.client.force_authenticate(user=self.user)

    def test_random_question_excludes_deleted_quizzes(self):
        trash_folder = Folder.objects.get(owner=self.user, folder_type=FolderType.TRASH)
        deleted_quiz = Quiz.objects.create(
            title="Deleted Quiz",
            creator=self.user,
            folder=trash_folder,
            deleted_at=timezone.now(),
        )
        Question.objects.create(quiz=deleted_quiz, order=1, text="Deleted question")
        QuizSession.objects.create(quiz=deleted_quiz, user=self.user, is_active=True)

        response = self.client.get(reverse("random-question"))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
