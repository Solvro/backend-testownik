from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Folder, Quiz

User = get_user_model()


class RootFolderTests(APITestCase):
    def test_root_folder_created_on_user_creation(self):
        """post_save signal creates root folder for new users."""
        user = User.objects.create_user(
            email="test@example.com", password="password123", first_name="Test", last_name="User"
        )
        user.refresh_from_db()
        self.assertIsNotNone(user.root_folder)
        self.assertEqual(user.root_folder.owner, user)
        self.assertEqual(user.root_folder.name, Folder.DEFAULT_ROOT_NAME)

    def test_root_folder_cannot_be_deleted(self):
        """Deleting a root folder raises ProtectedError."""
        user = User.objects.create_user(
            email="test@example.com", password="password123", first_name="Test", last_name="User"
        )
        user.refresh_from_db()
        with self.assertRaises(ProtectedError):
            user.root_folder.delete()

    def test_folder_deletion_blocked_when_has_quizzes(self):
        """Deleting a folder that contains quizzes raises ProtectedError."""
        user = User.objects.create_user(
            email="test@example.com", password="password123", first_name="Test", last_name="User"
        )
        user.refresh_from_db()
        folder = Folder.objects.create(name="Temp", owner=user, parent=user.root_folder)
        Quiz.objects.create(title="Temp Quiz", creator=user, folder=folder)

        with self.assertRaises(ProtectedError):
            folder.delete()

    def test_empty_folder_can_be_deleted(self):
        """Deleting a folder without quizzes succeeds."""
        user = User.objects.create_user(
            email="test@example.com", password="password123", first_name="Test", last_name="User"
        )
        user.refresh_from_db()
        folder = Folder.objects.create(name="Empty", owner=user, parent=user.root_folder)
        folder_id = folder.id

        folder.delete()
        self.assertFalse(Folder.objects.filter(id=folder_id).exists())

    def test_unique_root_folder_per_user(self):
        """Each user gets exactly one root folder, not duplicated on save."""
        user = User.objects.create_user(
            email="unique@example.com", password="password123", first_name="Unique", last_name="User"
        )
        user.refresh_from_db()
        root_id = user.root_folder_id

        user.save()
        user.refresh_from_db()
        self.assertEqual(user.root_folder_id, root_id)
        self.assertEqual(Folder.objects.filter(root_owner=user).count(), 1)

    def test_cannot_move_root_folder(self):
        """Root folders cannot be moved into other folders."""
        user = User.objects.create_user(
            email="move@example.com", password="password123", first_name="Move", last_name="User"
        )
        user.refresh_from_db()
        self.client.force_authenticate(user=user)
        other_folder = Folder.objects.create(name="Other", owner=user, parent=user.root_folder)
        url = reverse("folder-move", kwargs={"pk": user.root_folder.id})
        response = self.client.post(url, {"parent_id": str(other_folder.id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("The root folder cannot be moved.", str(response.data))
        user.root_folder.refresh_from_db()
        self.assertIsNone(user.root_folder.parent_id)

    def test_cannot_delete_root_folder(self):
        """Root folders cannot be deleted via API."""
        user = User.objects.create_user(
            email="del@example.com", password="password123", first_name="Del", last_name="User"
        )
        user.refresh_from_db()
        self.client.force_authenticate(user=user)
        url = reverse("folder-detail", kwargs={"pk": user.root_folder.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Folder.objects.filter(id=user.root_folder.id).exists())
