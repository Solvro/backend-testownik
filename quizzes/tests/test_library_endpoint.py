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

    def test_nested_folder_deletion_cascades(self):
        """Deleting a parent folder cascades to subfolders and their quizzes."""
        user = User.objects.create_user(
            email="test@example.com", password="password123", first_name="Test", last_name="User"
        )
        user.refresh_from_db()
        parent = Folder.objects.create(name="Parent", owner=user, parent=user.root_folder)
        child = Folder.objects.create(name="Child", owner=user, parent=parent)
        quiz_in_child = Quiz.objects.create(title="Child Quiz", creator=user, folder=child)

        parent.delete()
        self.assertFalse(Folder.objects.filter(id=child.id).exists())
        self.assertFalse(Quiz.objects.filter(id=quiz_in_child.id).exists())

    def test_empty_root_folder_returns_empty_list(self):
        """New user with no quizzes gets empty library response."""
        user = User.objects.create_user(
            email="empty@example.com", password="password123", first_name="Empty", last_name="User"
        )
        self.client.force_authenticate(user=user)
        response = self.client.get(reverse("library-root"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_unauthenticated_library_access(self):
        """Unauthenticated request to /library returns 401."""
        response = self.client.get(reverse("library-root"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cannot_access_other_users_root_folder(self):
        """User B cannot browse User A's root folder."""
        user_a = User.objects.create_user(
            email="a@example.com", password="password123", first_name="A", last_name="User"
        )
        user_b = User.objects.create_user(
            email="b@example.com", password="password123", first_name="B", last_name="User"
        )
        self.client.force_authenticate(user=user_b)

        url = reverse("library-folder", kwargs={"folder_id": user_a.root_folder_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_root_via_api_blocked(self):
        """DELETE /folders/{root_id}/ is blocked."""
        user = User.objects.create_user(
            email="del@example.com", password="password123", first_name="Del", last_name="User"
        )
        user.refresh_from_db()
        self.client.force_authenticate(user=user)

        url = reverse("folder-detail", kwargs={"pk": user.root_folder_id})
        response = self.client.delete(url)
        self.assertNotEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(Folder.objects.filter(id=user.root_folder_id).exists())

    def test_move_folder_to_root(self):
        """Moving a folder to root folder works via API."""
        user = User.objects.create_user(
            email="move@example.com", password="password123", first_name="Move", last_name="User"
        )
        user.refresh_from_db()
        self.client.force_authenticate(user=user)

        parent = Folder.objects.create(name="Parent", owner=user, parent=user.root_folder)
        child = Folder.objects.create(name="Child", owner=user, parent=parent)

        url = reverse("folder-move", kwargs={"pk": child.id})
        response = self.client.post(url, {"parent_id": str(user.root_folder_id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        child.refresh_from_db()
        self.assertEqual(child.parent_id, user.root_folder_id)

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

    def test_cannot_delete_other_users_folder(self):
        """DELETE /folders/{id}/ on another user's folder returns 404."""
        other = User.objects.create_user(
            email="other@example.com", password="password123", first_name="Other", last_name="User"
        )
        other.refresh_from_db()
        folder = Folder.objects.create(name="Other's Folder", owner=other, parent=other.root_folder)

        url = reverse("folder-detail", kwargs={"pk": folder.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Folder.objects.filter(id=folder.id).exists())

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
