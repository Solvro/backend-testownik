from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Folder, Quiz, Type
from users.models import User


class QuizArchiveTests(APITestCase):
    def setUp(self):
        self.user = User(email="quiz_archive_test@example.com", first_name="Test", last_name="User")
        self.user.set_password("password")
        self.user.save()
        self.client.force_authenticate(user=self.user)
        self.quiz = Quiz.objects.create(title="Test Quiz", maintainer=self.user)

    def test_archive_quiz_success(self):
        url = f"/quizzes/{self.quiz.id}/move-to-archive/"
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.folder.folder_type, Type.ARCHIVE)

    def test_move_quiz_from_regular_folder_to_archive(self):
        regular_folder = Folder.objects.create(name="Regular", owner=self.user)
        self.quiz.folder = regular_folder
        self.quiz.save()

        url = f"/quizzes/{self.quiz.id}/move-to-archive/"
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.folder.folder_type, Type.ARCHIVE)

    def test_archive_missing_folder_handling(self):
        Folder.objects.filter(owner=self.user, folder_type=Type.ARCHIVE).delete()

        url = f"/quizzes/{self.quiz.id}/move-to-archive/"
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_archive_quiz_twice_is_idempotent(self):
        archive_folder = Folder.objects.get(owner=self.user, folder_type=Type.ARCHIVE)
        self.quiz.folder = archive_folder
        self.quiz.save()

        url = f"/quizzes/{self.quiz.id}/move-to-archive/"
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.folder, archive_folder)

    def test_cannot_archive_other_users_quiz(self):
        other_user = User(email="other@example.com", first_name="Other", last_name="User")
        other_user.set_password("password")
        other_user.save()
        other_quiz = Quiz.objects.create(title="Other Quiz", maintainer=other_user)

        url = f"/quizzes/{other_quiz.id}/move-to-archive/"
        response = self.client.post(url)

        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_unauthenticated_cannot_archive_quiz(self):
        self.client.logout()
        url = f"/quizzes/{self.quiz.id}/move-to-archive/"
        response = self.client.post(url)

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_archive_nonexistent_quiz(self):
        url = "/quizzes/00000000-0000-0000-0000-000000000000/move-to-archive/"
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class FolderArchiveProtectionTests(APITestCase):
    def setUp(self):
        self.user = User(email="folder_test@example.com", first_name="Test", last_name="User")
        self.user.set_password("password")
        self.user.save()
        self.client.force_authenticate(user=self.user)
        self.archive_folder = Folder.objects.get(owner=self.user, folder_type=Type.ARCHIVE)

    def test_archive_folder_created_automatically(self):
        archive_exists = Folder.objects.filter(owner=self.user, folder_type=Type.ARCHIVE).exists()

        self.assertTrue(archive_exists)

    def test_cannot_delete_archive_folder(self):
        url = f"/folders/{self.archive_folder.id}/"
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Folder.objects.filter(id=self.archive_folder.id).exists())

    def test_cannot_rename_archive_folder(self):
        url = f"/folders/{self.archive_folder.id}/"
        response = self.client.patch(url, {"name": "New Name"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.archive_folder.refresh_from_db()
        self.assertNotEqual(self.archive_folder.name, "New Name")

    def test_cannot_move_archive_folder(self):
        regular_folder = Folder.objects.create(name="Regular", owner=self.user)
        url = f"/folders/{self.archive_folder.id}/move/"
        response = self.client.post(url, {"parent_id": str(regular_folder.id)})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.archive_folder.refresh_from_db()
        self.assertIsNone(self.archive_folder.parent)

    def test_cannot_make_archive_subfolder_via_patch(self):
        target_folder = Folder.objects.create(name="Regular", owner=self.user)
        url = f"/folders/{self.archive_folder.id}/"
        response = self.client.patch(url, {"parent": str(target_folder.id)})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.archive_folder.refresh_from_db()
        self.assertIsNone(self.archive_folder.parent)

    def test_cannot_create_subfolder_in_archive(self):
        url = "/folders/"
        response = self.client.post(url, {"name": "Subfolder", "parent": str(self.archive_folder.id)})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_move_folder_into_archive(self):
        regular_folder = Folder.objects.create(name="Regular", owner=self.user)
        url = f"/folders/{regular_folder.id}/move/"
        response = self.client.post(url, {"parent_id": str(self.archive_folder.id)})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        regular_folder.refresh_from_db()
        self.assertNotEqual(regular_folder.parent_id, self.archive_folder.id)

    def test_cannot_change_archive_folder_type(self):
        url = f"/folders/{self.archive_folder.id}/"
        response = self.client.patch(url, {"folder_type": Type.REGULAR})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.archive_folder.refresh_from_db()
        self.assertEqual(self.archive_folder.folder_type, Type.ARCHIVE)

    def test_each_user_has_separate_archive_folder(self):
        other_user = User(email="other@example.com", first_name="Other", last_name="User")
        other_user.set_password("password")
        other_user.save()

        other_archive = Folder.objects.get(owner=other_user, folder_type=Type.ARCHIVE)

        self.assertNotEqual(self.archive_folder.id, other_archive.id)
        self.assertEqual(self.archive_folder.owner, self.user)
        self.assertEqual(other_archive.owner, other_user)

    def test_user_cannot_access_other_users_archive(self):
        other_user = User(email="other@example.com", first_name="Other", last_name="User")
        other_user.set_password("password")
        other_user.save()
        other_archive = Folder.objects.get(owner=other_user, folder_type=Type.ARCHIVE)

        url = f"/folders/{other_archive.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_regular_folder_can_be_deleted(self):
        regular_folder = Folder.objects.create(name="Regular", owner=self.user)
        url = f"/folders/{regular_folder.id}/"
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Folder.objects.filter(id=regular_folder.id).exists())
