from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Folder, Quiz

User = get_user_model()


class FolderPermissionTests(APITestCase):
    """Tests for folder-based quiz permissions."""

    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com", password="password123", first_name="Owner", last_name="User"
        )
        self.owner.refresh_from_db()
        self.other = User.objects.create_user(
            email="other@example.com", password="password123", first_name="Other", last_name="User"
        )
        self.other.refresh_from_db()

    def test_folder_owner_can_edit_quiz_they_didnt_create(self):
        """Folder owner can edit a quiz even if they didn't create it."""
        quiz = Quiz.objects.create(title="By Other", creator=self.other, folder=self.owner.root_folder)

        self.client.force_authenticate(user=self.owner)
        url = reverse("quiz-detail", kwargs={"pk": quiz.id})
        response = self.client.put(url, {"title": "Edited by Owner", "questions": []}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        quiz.refresh_from_db()
        self.assertEqual(quiz.title, "Edited by Owner")

    def test_creator_cannot_edit_quiz_in_other_users_folder(self):
        """Quiz creator cannot edit quiz if it's in someone else's folder."""
        quiz = Quiz.objects.create(title="My Quiz", creator=self.other, folder=self.owner.root_folder)

        self.client.force_authenticate(user=self.other)
        url = reverse("quiz-detail", kwargs={"pk": quiz.id})
        response = self.client.put(url, {"title": "Hacked", "questions": []}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        quiz.refresh_from_db()
        self.assertEqual(quiz.title, "My Quiz")

    def test_folder_owner_can_delete_quiz(self):
        """Folder owner can delete quiz even if created by someone else."""
        quiz = Quiz.objects.create(title="Delete Me", creator=self.other, folder=self.owner.root_folder)

        self.client.force_authenticate(user=self.owner)
        url = reverse("quiz-detail", kwargs={"pk": quiz.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Quiz.objects.filter(id=quiz.id).exists())

    def test_creator_cannot_delete_quiz_in_other_users_folder(self):
        """Quiz creator cannot delete quiz if it's in someone else's folder."""
        quiz = Quiz.objects.create(title="Not Yours", creator=self.other, folder=self.owner.root_folder)

        self.client.force_authenticate(user=self.other)
        url = reverse("quiz-detail", kwargs={"pk": quiz.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Quiz.objects.filter(id=quiz.id).exists())


class FolderCRUDTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="crud@example.com", password="password123", first_name="Crud", last_name="User"
        )
        self.user.refresh_from_db()
        self.client.force_authenticate(user=self.user)

    def test_create_folder_via_api(self):
        """POST /folders/ creates a new folder owned by the user."""
        url = reverse("folder-list")
        response = self.client.post(
            url, {"name": "Nowy Folder", "parent": str(self.user.root_folder_id)}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        folder = Folder.objects.get(id=response.data["id"])
        self.assertEqual(folder.name, "Nowy Folder")
        self.assertEqual(folder.owner, self.user)
        self.assertEqual(folder.parent_id, self.user.root_folder_id)

    def test_rename_folder_via_api(self):
        """PATCH /folders/{id}/ renames the folder."""
        folder = Folder.objects.create(name="Old Name", owner=self.user, parent=self.user.root_folder)
        url = reverse("folder-detail", kwargs={"pk": folder.id})
        response = self.client.patch(url, {"name": "New Name"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        folder.refresh_from_db()
        self.assertEqual(folder.name, "New Name")

    def test_move_quiz_between_folders(self):
        """POST /quizzes/{id}/move/ moves quiz to another folder."""
        folder_a = Folder.objects.create(name="A", owner=self.user, parent=self.user.root_folder)
        folder_b = Folder.objects.create(name="B", owner=self.user, parent=self.user.root_folder)
        quiz = Quiz.objects.create(title="Movable", creator=self.user, folder=folder_a)

        url = reverse("quiz-move", kwargs={"pk": quiz.id})
        response = self.client.post(url, {"folder_id": str(folder_b.id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        quiz.refresh_from_db()
        self.assertEqual(quiz.folder_id, folder_b.id)

    def test_move_folder_to_root(self):
        """Moving a folder to root folder works via API."""
        parent = Folder.objects.create(name="Parent", owner=self.user, parent=self.user.root_folder)
        child = Folder.objects.create(name="Child", owner=self.user, parent=parent)

        url = reverse("folder-move", kwargs={"pk": child.id})
        response = self.client.post(url, {"parent_id": str(self.user.root_folder_id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        child.refresh_from_db()
        self.assertEqual(child.parent_id, self.user.root_folder_id)

    def test_cannot_rename_other_users_folder(self):
        """PATCH /folders/{id}/ on another user's folder returns 404."""
        other = User.objects.create_user(
            email="other@example.com", password="password123", first_name="Other", last_name="User"
        )
        other.refresh_from_db()
        folder = Folder.objects.create(name="Private", owner=other, parent=other.root_folder)

        url = reverse("folder-detail", kwargs={"pk": folder.id})
        response = self.client.patch(url, {"name": "Hacked"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        folder.refresh_from_db()
        self.assertEqual(folder.name, "Private")

    def test_cannot_move_quiz_to_other_users_folder(self):
        """Moving quiz to another user's folder fails validation."""
        other = User.objects.create_user(
            email="other@example.com", password="password123", first_name="Other", last_name="User"
        )
        other.refresh_from_db()
        other_folder = Folder.objects.create(name="Other's", owner=other, parent=other.root_folder)
        quiz = Quiz.objects.create(title="My Quiz", creator=self.user, folder=self.user.root_folder)

        url = reverse("quiz-move", kwargs={"pk": quiz.id})
        response = self.client.post(url, {"folder_id": str(other_folder.id)}, format="json")
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN])
        quiz.refresh_from_db()
        self.assertEqual(quiz.folder_id, self.user.root_folder_id)

    def test_cannot_create_folder_in_other_users_folder(self):
        """Creating a folder with another user's folder as parent is rejected."""
        other = User.objects.create_user(
            email="other2@example.com", password="password123", first_name="Other", last_name="User"
        )
        other.refresh_from_db()

        url = reverse("folder-list")
        response = self.client.post(url, {"name": "Sneaky Folder", "parent": str(other.root_folder_id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Folder.objects.filter(name="Sneaky Folder").exists())
