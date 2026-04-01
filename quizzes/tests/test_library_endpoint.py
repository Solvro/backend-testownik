from django.contrib.auth import get_user_model
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

        returned_ids = {str(item["id"]) for item in response.data["items"]}
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
        returned_names = {item.get("name") for item in response.data["items"] if item.get("type") == "quiz"}
        self.assertIn("Hidden Quiz", returned_names)

    def test_study_group_sharing(self):
        """Folder shared via study group is accessible."""
        SharedFolder.objects.create(folder=self.folder_main, study_group=self.group)
        SharedFolder.objects.create(folder=self.folder_sub, study_group=self.group)

        self.client.force_authenticate(user=self.user_b)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_main.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_names = {item.get("name") for item in response.data["items"] if item.get("type") == "folder"}
        self.assertIn("Sub", returned_names)

    def test_authorized_folder_access(self):
        """Browsing a shared folder returns its contents."""
        SharedFolder.objects.create(folder=self.folder_main, user=self.user_b)
        SharedFolder.objects.create(folder=self.folder_sub, user=self.user_b)

        self.client.force_authenticate(user=self.user_b)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_main.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {str(item["id"]) for item in response.data["items"]}
        self.assertIn(str(self.folder_sub.id), returned_ids)

    def test_unauthorized_folder_access(self):
        """User without access gets 403."""
        self.client.force_authenticate(user=self.user_b)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_main.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cascading_access_to_subfolder(self):
        """Sharing a parent folder gives access to its subfolders without separate shares."""
        SharedFolder.objects.create(folder=self.folder_main, user=self.user_b)

        self.client.force_authenticate(user=self.user_b)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_sub.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_names = {item.get("name") for item in response.data["items"] if item.get("type") == "quiz"}
        self.assertIn("Hidden Quiz", returned_names)


class LibraryBreadcrumbTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com", password="password123", first_name="Jan", last_name="Kowalski"
        )
        self.viewer = User.objects.create_user(
            email="viewer@example.com", password="password123", first_name="Anna", last_name="Nowak"
        )

        # owner's root folder auto-created ("Moje quizy")
        self.folder_a = Folder.objects.create(name="A", owner=self.owner, parent=self.owner.root_folder)
        self.folder_b = Folder.objects.create(name="B", owner=self.owner, parent=self.folder_a)
        self.folder_c = Folder.objects.create(name="C", owner=self.owner, parent=self.folder_b)

    def test_owner_root_breadcrumbs(self):
        """Owner viewing root folder gets path with just the root folder."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(reverse("library-root"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        path = response.data["path"]
        self.assertEqual(len(path), 1)
        self.assertEqual(path[0]["id"], str(self.owner.root_folder.id))
        self.assertEqual(path[0]["name"], "Moje quizy")

    def test_owner_nested_breadcrumbs(self):
        """Owner viewing nested folder gets full path from root."""
        self.client.force_authenticate(user=self.owner)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_c.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        path = response.data["path"]
        self.assertEqual(len(path), 4)
        self.assertEqual(path[0]["name"], "Moje quizy")
        self.assertEqual(path[1]["name"], "A")
        self.assertEqual(path[2]["name"], "B")
        self.assertEqual(path[3]["name"], "C")

    def test_shared_user_breadcrumbs_start_at_shared_folder(self):
        """Viewer with shared access sees breadcrumbs starting from shared folder."""
        SharedFolder.objects.create(folder=self.folder_a, user=self.viewer)

        self.client.force_authenticate(user=self.viewer)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_c.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        path = response.data["path"]
        # Should start from A (first directly shared ancestor), not root
        self.assertEqual(len(path), 3)
        self.assertEqual(path[0]["name"], "A")
        self.assertEqual(path[1]["name"], "B")
        self.assertEqual(path[2]["name"], "C")

    def test_shared_user_breadcrumbs_direct_access(self):
        """Viewer viewing the directly shared folder gets just that folder in path."""
        SharedFolder.objects.create(folder=self.folder_b, user=self.viewer)

        self.client.force_authenticate(user=self.viewer)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_b.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        path = response.data["path"]
        self.assertEqual(len(path), 1)
        self.assertEqual(path[0]["name"], "B")

    def test_response_has_path_and_items_keys(self):
        """Response contains both 'path' and 'items' keys."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(reverse("library-root"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("path", response.data)
        self.assertIn("items", response.data)
