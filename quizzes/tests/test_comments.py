from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from quizzes.models import Comment, Quiz, SharedQuiz

User = get_user_model()


class CommentViewSetTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="example_1@mail.com", password="password")
        self.other_user = User.objects.create_user(email="example_2@mail.com", password="password")
        self.quiz = Quiz.objects.create(title="Test Quiz", maintainer=self.user)
        self.shared_quiz = SharedQuiz.objects.create(quiz=self.quiz, user=self.user)
        self.comment = Comment.objects.create(
            author=self.user,
            content="Test comment",
            shared_quiz=self.shared_quiz,
        )
        self.client.force_authenticate(user=self.user)

    def test_list_comments(self):
        response = self.client.get("/api/comments/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_comment(self):
        response = self.client.post(
            "/api/comments/",
            {
                "content": "New comment",
                "shared_quiz": self.shared_quiz.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_comment_empty_content(self):
        response = self.client.post(
            "/api/comments/",
            {
                "content": "   ",
                "shared_quiz": self.shared_quiz.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_comment_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/comments/",
            {
                "content": "New comment",
                "shared_quiz": self.shared_quiz.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_reply(self):
        response = self.client.post(
            "/api/comments/",
            {
                "content": "Reply comment",
                "shared_quiz": self.shared_quiz.id,
                "parent": self.comment.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["parent"], self.comment.id)

    # UPDATE
    def test_update_own_comment(self):
        response = self.client.patch(
            f"/api/comments/{self.comment.id}/",
            {
                "content": "Updated comment",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["content"], "Updated comment")

    def test_update_other_user_comment(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.patch(
            f"/api/comments/{self.comment.id}/",
            {
                "content": "Hacked comment",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # DELETE
    def test_soft_delete_own_comment(self):
        response = self.client.delete(f"/api/comments/{self.comment.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.comment.refresh_from_db()
        self.assertTrue(self.comment.is_deleted)
        self.assertIsNone(self.comment.author)
        self.assertEqual(self.comment.content, "")

    def test_delete_other_user_comment(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.delete(f"/api/comments/{self.comment.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_already_deleted_comment(self):
        self.comment.mark_as_deleted()
        response = self.client.delete(f"/api/comments/{self.comment.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # SERIALIZER
    def test_deleted_comment_hides_content(self):
        self.comment.mark_as_deleted()
        response = self.client.get(f"/api/comments/{self.comment.id}/")

        self.assertIsNone(response.data["content"])
        self.assertIsNone(response.data["author"])
