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

        self.quiz = Quiz.objects.create(title="Test Quiz", creator=self.user, folder=self.folder)
        self.question = Question.objects.create(quiz=self.quiz, text="What is 2+2?", order=1)

        self.comment = Comment.objects.create(
            author=self.user,
            content="Test comment",
            quiz=self.quiz,
        )
        self.client.force_authenticate(user=self.user)

    def test_list_comments(self):
        response = self.client.get(f"/api/comments/?quiz={self.quiz.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_comments_requires_quiz_param(self):
        response = self.client.get("/api/comments/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_me_comments(self):
        response = self.client.get("/api/comments/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        # Verify it's the own comment
        self.assertEqual(response.data[0]["id"], str(self.comment.id))

    def test_create_comment_to_quiz(self):
        response = self.client.post(
            "/api/comments/",
            {
                "content": "New quiz comment",
                "quiz": self.quiz.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["quiz"], self.quiz.id)

    def test_create_comment_to_question(self):
        response = self.client.post(
            "/api/comments/",
            {
                "content": "Question feedback",
                "question": self.question.id,
                "quiz": self.quiz.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["question"], self.question.id)

    def test_create_comment_empty_content(self):
        response = self.client.post(
            "/api/comments/",
            {
                "content": "   ",
                "quiz": self.quiz.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_comment_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/comments/",
            {"content": "New comment", "quiz": self.quiz.id},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_reply(self):
        response = self.client.post(
            "/api/comments/",
            {
                "content": "Reply comment",
                "parent": self.comment.id,
                "quiz": self.quiz.id,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["parent"], self.comment.id)

    # UPDATE
    def test_update_own_comment(self):
        response = self.client.patch(
            f"/api/comments/{self.comment.id}/",
            {"content": "Updated comment"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["content"], "Updated comment")

    def test_update_other_user_comment(self):
        # The private quiz is not visible to other_user, so get_queryset filters
        # the comment out before the permission check — expect 404.
        self.quiz.visibility = 0
        self.quiz.save()
        self.client.force_authenticate(user=self.other_user)
        response = self.client.patch(
            f"/api/comments/{self.comment.id}/",
            {"content": "Hacked comment"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # DELETE
    def test_soft_delete_own_comment(self):
        response = self.client.delete(f"/api/comments/{self.comment.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.comment.refresh_from_db()
        self.assertTrue(self.comment.is_deleted)
        # Author is preserved on the DB row (attribution is intentional).
        self.assertEqual(self.comment.author, self.user)
        self.assertTrue(self.comment.content)

        # GET hides the content but still attributes the comment.
        response = self.client.get(f"/api/comments/{self.comment.id}/")
        self.assertEqual(response.data["content"], "")
        self.assertEqual(response.data["author"]["id"], str(self.user.id))

    def test_deleted_comment_hides_content(self):
        self.comment.mark_as_deleted()

        response = self.client.get(f"/api/comments/{self.comment.id}/")

        self.assertEqual(response.data["content"], "")
        self.assertEqual(response.data["author"]["id"], str(self.user.id))

    def test_cannot_comment_on_inaccessible_quiz(self):
        self.quiz.visibility = 0
        self.quiz.save(update_fields=["visibility"])

        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(
            "/api/comments/",
            {"content": "I should not be able to post this", "quiz": self.quiz.id},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Comment.objects.filter(content="I should not be able to post this").exists())

    def test_cannot_reply_to_deleted_comment(self):
        self.comment.mark_as_deleted()
        response = self.client.post(
            "/api/comments/",
            {"content": "Reply to a ghost", "parent": self.comment.id, "quiz": self.quiz.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent", response.data)

    def test_reply_to_reply_is_flattened_to_top_level(self):
        reply = Comment.objects.create(author=self.user, content="First reply", quiz=self.quiz, parent=self.comment)
        response = self.client.post(
            "/api/comments/",
            {"content": "Nested reply", "parent": reply.id, "quiz": self.quiz.id},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Parent was flattened to the top-level comment, not the intermediate reply.
        self.assertEqual(response.data["parent"], self.comment.id)

    def test_question_from_other_quiz_is_rejected(self):
        other_quiz = Quiz.objects.create(title="Other quiz", creator=self.user, folder=self.folder)
        foreign_question = Question.objects.create(quiz=other_quiz, text="Other?", order=1)

        response = self.client.post(
            "/api/comments/",
            {"content": "Cross-quiz question ref", "question": foreign_question.id, "quiz": self.quiz.id},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("question", response.data)
