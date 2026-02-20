from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Folder, Quiz, SharedFolder
from users.models import StudyGroup

User = get_user_model()


class LibraryTests(APITestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            email="user_a@example.com", password="password123", first_name="Jan", last_name="Kowalski"
        )
        self.user_b = User.objects.create_user(
            email="user_b@example.com", password="password123", first_name="Anna", last_name="Nowak"
        )

        self.group = StudyGroup.objects.create(id="test-group", name="Solvro Group")
        self.group.members.add(self.user_b)

        # user_a's root folder is auto-created by signal
        self.folder_main = Folder.objects.create(name="Main", owner=self.user_a, parent=self.user_a.root_folder)
        self.folder_sub = Folder.objects.create(name="Sub", owner=self.user_a, parent=self.folder_main)

        self.quiz_hidden = Quiz.objects.create(title="Hidden Quiz", creator=self.user_a, folder=self.folder_sub)
        self.quiz_root = Quiz.objects.create(title="Root Quiz", creator=self.user_a, folder=self.user_a.root_folder)

    def test_root_shows_only_own_toplevel_items(self):
        """GET /library returns items from user's root folder."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(reverse("library-root"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        returned_ids = {str(item["id"]) for item in response.data}
        # Root folder should contain: Main folder + Root Quiz
        expected_ids = {str(self.folder_main.id), str(self.quiz_root.id)}
        self.assertEqual(returned_ids, expected_ids)

        # Sub folder and hidden quiz should NOT appear at root level
        self.assertNotIn(str(self.folder_sub.id), returned_ids)
        self.assertNotIn(str(self.quiz_hidden.id), returned_ids)

    def test_shared_folder_visible_in_root(self):
        """Shared folders are accessible and show their content."""
        SharedFolder.objects.create(folder=self.folder_sub, user=self.user_b)

        self.client.force_authenticate(user=self.user_b)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_sub.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_titles = {item.get("title") for item in response.data if item.get("type") == "quiz"}
        self.assertIn("Hidden Quiz", returned_titles)

    def test_study_group_sharing(self):
        """Folder shared via study group is accessible."""
        SharedFolder.objects.create(folder=self.folder_main, study_group=self.group)
        SharedFolder.objects.create(folder=self.folder_sub, study_group=self.group)

        self.client.force_authenticate(user=self.user_b)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_main.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_names = {item.get("name") for item in response.data if item.get("type") == "folder"}
        self.assertIn("Sub", returned_names)

    def test_authorized_folder_access(self):
        """Browsing a shared folder returns its contents."""
        SharedFolder.objects.create(folder=self.folder_main, user=self.user_b)
        SharedFolder.objects.create(folder=self.folder_sub, user=self.user_b)

        self.client.force_authenticate(user=self.user_b)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_main.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {str(item["id"]) for item in response.data}
        self.assertIn(str(self.folder_sub.id), returned_ids)

    def test_unauthorized_folder_access(self):
        """User without access gets 403."""
        self.client.force_authenticate(user=self.user_b)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_main.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class RootFolderTests(APITestCase):
    def test_root_folder_created_on_user_creation(self):
        """post_save signal creates root folder for new users."""
        user = User.objects.create_user(
            email="test@example.com", password="password123", first_name="Test", last_name="User"
        )
        user.refresh_from_db()
        self.assertIsNotNone(user.root_folder)
        self.assertEqual(user.root_folder.owner, user)
        self.assertEqual(user.root_folder.name, "Moje quizy")

    def test_root_folder_cannot_be_deleted(self):
        """Deleting a root folder raises ProtectedError."""
        user = User.objects.create_user(
            email="test@example.com", password="password123", first_name="Test", last_name="User"
        )
        user.refresh_from_db()
        with self.assertRaises(ProtectedError):
            user.root_folder.delete()

    def test_folder_deletion_cascades_to_quizzes(self):
        """Deleting a non-root folder cascades and deletes its quizzes."""
        user = User.objects.create_user(
            email="test@example.com", password="password123", first_name="Test", last_name="User"
        )
        user.refresh_from_db()
        folder = Folder.objects.create(name="Temp", owner=user, parent=user.root_folder)
        quiz = Quiz.objects.create(title="Temp Quiz", creator=user, folder=folder)

        folder.delete()
        self.assertFalse(Quiz.objects.filter(id=quiz.id).exists())
