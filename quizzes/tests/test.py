from rest_framework import status
from rest_framework.test import APITestCase
from users.models import User
from quizzes.models import Folder


class FolderArchiveTests(APITestCase):
    def setUp(self):
        self.user = User(email='archive_test@example.com', first_name='Test', last_name='User')
        self.user.set_password('password')
        self.user.save()
        self.client.force_authenticate(user=self.user)

    def test_archive_folder_created_automatically(self):
        archive_exists = Folder.objects.filter(
            owner=self.user,
            folder_type=Folder.Type.ARCHIVE
        ).exists()

        self.assertTrue(archive_exists, "Folder Archiwum nie został utworzony automatycznie przez sygnał!")

    def test_cannot_delete_archive_folder(self):
        archive = Folder.objects.get(owner=self.user, folder_type=Folder.Type.ARCHIVE)
        url = f'/folders/{archive.id}/'
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Folder.objects.filter(id=archive.id).exists())

    def test_cannot_rename_archive_folder(self):
        archive = Folder.objects.get(owner=self.user, folder_type=Folder.Type.ARCHIVE)
        url = f'/folders/{archive.id}/'
        data = {"name": "Hacker Folder"}
        response = self.client.patch(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        archive.refresh_from_db()
        self.assertEqual(archive.name, "Archive")

    def test_cannot_move_archive_folder_via_action(self):
        archive = Folder.objects.get(owner=self.user, folder_type=Folder.Type.ARCHIVE)
        target_folder = Folder.objects.create(name="Zwykły Folder", owner=self.user)
        url = f'/folders/{archive.id}/move/'
        data = {"parent_id": target_folder.id}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        archive.refresh_from_db()
        self.assertIsNone(archive.parent, "Archiwum nie powinno mieć rodzica")

    def test_cannot_make_archive_a_subfolder_via_patch(self):
        archive = Folder.objects.get(owner=self.user, folder_type=Folder.Type.ARCHIVE)
        target_folder = Folder.objects.create(name="Inny", owner=self.user)
        url = f'/folders/{archive.id}/'
        data = {"parent": target_folder.id}
        response = self.client.patch(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)