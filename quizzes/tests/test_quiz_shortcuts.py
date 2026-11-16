from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Folder, Quiz, QuizShortcut, SharedQuiz
from users.models import User


class QuizShortcutTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="password123")
        self.reader = User.objects.create_user(email="reader@example.com", password="password123")
        self.stranger = User.objects.create_user(email="stranger@example.com", password="password123")
        self.quiz = Quiz.objects.create(title="Shared", creator=self.owner, folder=self.owner.root_folder, visibility=1)
        SharedQuiz.objects.create(quiz=self.quiz, user=self.reader)
        self.folder = Folder.objects.create(name="Study", owner=self.reader, parent=self.reader.root_folder)
        self.other = Folder.objects.create(name="Later", owner=self.reader, parent=self.reader.root_folder)

    def create(self, user, quiz=None, folder=None):
        self.client.force_authenticate(user=user)
        return self.client.post(
            "/api/quiz-shortcuts/",
            {"quiz_id": str((quiz or self.quiz).id), "folder_id": str((folder or self.folder).id)},
            format="json",
        )

    def library_items(self, folder):
        self.client.force_authenticate(user=self.reader)
        return self.client.get(reverse("library-folder", args=[folder.id])).data["items"]

    def test_shortcut_lists_as_the_quiz_in_the_folder(self):
        response = self.create(self.reader)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        items = self.library_items(self.folder)
        self.assertEqual(len(items), 1)
        self.assertEqual(str(items[0]["id"]), str(self.quiz.id))
        self.assertEqual(str(items[0]["shortcut_id"]), str(response.data["id"]))
        self.assertFalse(items[0]["can_manage"])
        # Adding it again keeps a single shortcut.
        self.assertEqual(self.create(self.reader).status_code, status.HTTP_200_OK)
        self.assertEqual(QuizShortcut.objects.count(), 1)

    def test_unreadable_own_or_foreign_folder_is_rejected(self):
        self.assertEqual(self.create(self.stranger, folder=self.stranger.root_folder).status_code, 403)
        self.assertEqual(self.create(self.owner, folder=self.owner.root_folder).status_code, 400)
        self.assertEqual(self.create(self.reader, folder=self.owner.root_folder).status_code, 400)

    def test_move_and_delete(self):
        shortcut_id = self.create(self.reader).data["id"]
        response = self.client.post(
            f"/api/quiz-shortcuts/{shortcut_id}/move/", {"folder_id": str(self.other.id)}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self.library_items(self.folder)), 0)
        self.assertEqual(len(self.library_items(self.other)), 1)
        self.client.force_authenticate(user=self.stranger)
        self.assertEqual(self.client.delete(f"/api/quiz-shortcuts/{shortcut_id}/").status_code, 404)
        self.client.force_authenticate(user=self.reader)
        self.assertEqual(self.client.delete(f"/api/quiz-shortcuts/{shortcut_id}/").status_code, 204)
        self.assertFalse(QuizShortcut.objects.exists())

    def test_losing_access_hides_the_shortcut(self):
        self.create(self.reader)
        SharedQuiz.objects.all().delete()
        self.assertEqual(self.library_items(self.folder), [])
