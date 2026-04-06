from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from quizzes.models import Comment, Folder, Question, Quiz

User = get_user_model()


class CommentViewSetTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="example_1@mail.com", password="password1")
        self.other_user = User.objects.create_user(email="example_2@mail.com", password="password2")

        self.folder = Folder.objects.create(name="Test Folder", owner=self.user)

        # Tworzymy Quiz i pytanie do niego
        self.quiz = Quiz.objects.create(title="Test Quiz", creator=self.user, folder=self.folder)
        self.question = Question.objects.create(quiz=self.quiz, text="What is 2+2?", order=1)

        # Tworzymy komentarz przypisany bezpośrednio do Quizu
        self.comment = Comment.objects.create(
            author=self.user,
            content="Test comment",
            quiz=self.quiz,
        )
        self.client.force_authenticate(user=self.user)

    def test_list_comments(self):
        response = self.client.get(f"/api/quizzes/{self.quiz.id}/comments/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_comment_to_quiz(self):
        """Test tworzenia komentarza ogólnego do quizu"""
        response = self.client.post(
            f"/api/quizzes/{self.quiz.id}/comments/",
            {
                "content": "New quiz comment",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["quiz"], self.quiz.id)

    def test_create_comment_to_question(self):
        """Test tworzenia komentarza do konkretnego pytania"""
        response = self.client.post(
            f"/api/quizzes/{self.quiz.id}/comments/",
            {
                "content": "Question feedback",
                "question": self.question.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["question"], self.question.id)

    def test_create_comment_empty_content(self):
        response = self.client.post(
            f"/api/quizzes/{self.quiz.id}/comments/",
            {
                "content": "   ",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_comment_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            f"/api/quizzes/{self.quiz.id}/comments/",
            {"content": "New comment"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_reply(self):
        response = self.client.post(
            f"/api/quizzes/{self.quiz.id}/comments/",
            {
                "content": "Reply comment",
                "parent": self.comment.id,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["parent"], self.comment.id)

    # UPDATE
    def test_update_own_comment(self):
        response = self.client.patch(
            f"/api/quizzes/{self.quiz.id}/comments/{self.comment.id}/",
            {"content": "Updated comment"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["content"], "Updated comment")

    def test_update_other_user_comment(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.patch(
            f"/api/quizzes/{self.quiz.id}/comments/{self.comment.id}/",
            {"content": "Hacked comment"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Zmieniono na 404, bo Twoje get_queryset odfiltruje ten komentarz dla innego usera

    # DELETE
    def test_soft_delete_own_comment(self):
        response = self.client.delete(f"/api/quizzes/{self.quiz.id}/comments/{self.comment.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.comment.refresh_from_db()
        self.assertTrue(self.comment.is_deleted)
        self.assertIsNone(self.comment.author)
        self.assertTrue(self.comment.content)

        # teraz sprawdź GET
        response = self.client.get(f"/api/quizzes/{self.quiz.id}/comments/{self.comment.id}/")
        self.assertIsNone(response.data["content"])  # serializer zwraca None
        self.assertIsNone(response.data["author"])

    def test_deleted_comment_hides_content(self):
        self.comment.mark_as_deleted()

        response = self.client.get(f"/api/quizzes/{self.quiz.id}/comments/{self.comment.id}/")

        self.assertIsNone(response.data["content"])
        self.assertIsNone(response.data["author"])
