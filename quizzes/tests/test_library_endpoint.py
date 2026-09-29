from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Folder, FolderType, Question, Quiz, QuizSession, SharedFolder
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

    def test_last_used_is_requesting_users_activity_only(self):
        QuizSession.objects.create(quiz=self.quiz_root, user=self.user_b)
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(reverse("library-root"))
        item = next(item for item in response.data["items"] if str(item["id"]) == str(self.quiz_root.id))
        self.assertIsNone(item["last_used_at"])
        own = QuizSession.objects.create(quiz=self.quiz_root, user=self.user_a)
        earlier = timezone.now() - timedelta(days=2)
        QuizSession.objects.filter(pk=own.pk).update(updated_at=earlier)
        response = self.client.get(reverse("library-root"))
        item = next(item for item in response.data["items"] if str(item["id"]) == str(self.quiz_root.id))
        self.assertEqual(item["last_used_at"], earlier)

    def test_question_counts_do_not_multiply_with_sessions(self):
        Question.objects.create(quiz=self.quiz_root, text="One", order=0)
        Question.objects.create(quiz=self.quiz_root, text="Two", order=1)
        QuizSession.objects.create(quiz=self.quiz_root, user=self.user_a)
        QuizSession.objects.create(quiz=self.quiz_root, user=self.user_b)
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(reverse("library-root"))
        item = next(item for item in response.data["items"] if str(item["id"]) == str(self.quiz_root.id))
        self.assertEqual(item["question_count"], 2)
        response = self.client.get("/api/last-used-quizzes/")
        self.assertEqual(response.status_code, 200)
        item = next(
            item
            for item in (response.data["results"] if isinstance(response.data, dict) else response.data)
            if str(item["id"]) == str(self.quiz_root.id)
        )
        self.assertEqual(item["question_count"], 2)
        response = self.client.get("/api/search-quizzes/", {"query": "Root Quiz"})
        self.assertEqual(response.status_code, 200)
        item = next(item for item in response.data["user_quizzes"] if str(item["id"]) == str(self.quiz_root.id))
        self.assertEqual(item["question_count"], 2)
        self.assertIsNotNone(item["last_used_at"])

    def test_root_shows_only_own_toplevel_items(self):
        """GET /library returns items from user's root folder."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(reverse("library-root"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        returned_ids = {str(item["id"]) for item in response.data["items"]}
        # Root folder should contain: Main folder + Root Quiz + Archive folder + Trash folder
        archive_folder = Folder.objects.get(owner=self.user_a, folder_type="archive")
        trash_folder = Folder.objects.get(owner=self.user_a, folder_type="trash")
        expected_ids = {str(self.folder_main.id), str(self.quiz_root.id), str(archive_folder.id), str(trash_folder.id)}
        self.assertEqual(returned_ids, expected_ids)

        # Sub folder and hidden quiz should NOT appear at root level
        self.assertNotIn(str(self.folder_sub.id), returned_ids)
        self.assertNotIn(str(self.quiz_hidden.id), returned_ids)
        owned_quiz = next(item for item in response.data["items"] if str(item["id"]) == str(self.quiz_root.id))
        self.assertTrue(owned_quiz["can_manage"])

    def test_library_exposes_protected_folder_capabilities(self):
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(reverse("library-root"))
        self.assertTrue(response.data["can_create_folder"])
        protected = [item for item in response.data["items"] if item.get("folder_type") in ("trash", "archive")]
        self.assertEqual(len(protected), 2)
        for item in protected:
            response = self.client.get(reverse("library-folder", kwargs={"folder_id": item["id"]}))
            self.assertFalse(response.data["can_create_folder"])
        SharedFolder.objects.create(folder=self.folder_main, user=self.user_b)
        self.client.force_authenticate(user=self.user_b)
        response = self.client.get(reverse("library-folder", kwargs={"folder_id": self.folder_main.id}))
        self.assertFalse(response.data["can_create_folder"])

    def test_shared_folder_visible_in_root(self):
        """Shared folders are accessible and show their content."""
        SharedFolder.objects.create(folder=self.folder_sub, user=self.user_b)

        self.client.force_authenticate(user=self.user_b)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_sub.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_names = {item.get("name") for item in response.data["items"] if item.get("type") == "quiz"}
        self.assertIn("Hidden Quiz", returned_names)
        self.assertFalse(next(item for item in response.data["items"] if item["type"] == "quiz")["can_manage"])

    def test_shared_root_does_not_expose_trash(self):
        """Sharing a root folder does not give access to the owner's trash."""
        trash_folder = Folder.objects.get(owner=self.user_a, folder_type=FolderType.TRASH)
        deleted_quiz = Quiz.objects.create(title="Deleted Quiz", creator=self.user_a, folder=trash_folder)
        SharedFolder.objects.create(folder=self.user_a.root_folder, user=self.user_b)

        self.client.force_authenticate(user=self.user_b)
        response = self.client.get(reverse("library-folder", kwargs={"folder_id": self.user_a.root_folder.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {str(item["id"]) for item in response.data["items"]}
        returned_names = {item["name"] for item in response.data["items"]}
        self.assertNotIn(str(trash_folder.id), returned_ids)
        self.assertNotIn(deleted_quiz.title, returned_names)

        response = self.client.get(reverse("library-folder", kwargs={"folder_id": trash_folder.id}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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

        # owner's root folder auto-created (Folder.DEFAULT_ROOT_NAME)
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
        self.assertEqual(path[0]["name"], Folder.DEFAULT_ROOT_NAME)

    def test_owner_nested_breadcrumbs(self):
        """Owner viewing nested folder gets full path from root."""
        self.client.force_authenticate(user=self.owner)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_c.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        path = response.data["path"]
        self.assertEqual(len(path), 4)
        self.assertEqual(path[0]["name"], Folder.DEFAULT_ROOT_NAME)
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
