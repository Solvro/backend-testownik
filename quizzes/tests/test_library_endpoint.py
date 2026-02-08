from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Folder, Quiz, SharedFolder, StudyGroup

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

        self.folder_main = Folder.objects.create(name="Main", owner=self.user_a)
        self.folder_sub = Folder.objects.create(name="Sub", owner=self.user_a, parent=self.folder_main)

        self.quiz_hidden = Quiz.objects.create(title="Hidden Quiz", maintainer=self.user_a, folder=self.folder_sub)
        self.quiz_root = Quiz.objects.create(title="Root Quiz", maintainer=self.user_a, folder=None)

    def test_root_shows_only_own_toplevel_items(self):
        """Sprawdza dokładną zawartość root (IDs i brak elementow ukrytych)."""
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get(reverse("library-root"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Wyciągamy ID i nazwy wszystkich zwróconych elementów
        returned_ids = [str(item["id"]) for item in response.data]
        returned_names = [item.get("name") or item.get("title") for item in response.data]

        expected_ids = {str(self.folder_main.id), str(self.quiz_root.id)}
        self.assertEqual(set(returned_ids), expected_ids)

        self.assertNotIn(str(self.folder_sub.id), returned_ids)
        self.assertNotIn("Hidden Quiz", returned_names)

    def test_shared_subfolder_floats_to_root(self):
        """Sprawdza floating logic w sposób odporny na kolejność."""
        SharedFolder.objects.create(folder=self.folder_sub, user=self.user_b)

        self.client.force_authenticate(user=self.user_b)
        response = self.client.get(reverse("library-root"))

        returned_names = {item.get("name") for item in response.data}
        self.assertEqual(returned_names, {"Sub"})

    def test_study_group_sharing(self):
        """Sprawdza udostępnianie grupowe w sposób odporny na kolejność."""
        SharedFolder.objects.create(folder=self.folder_main, study_group=self.group)

        self.client.force_authenticate(user=self.user_b)
        response = self.client.get(reverse("library-root"))

        returned_names = {item.get("name") for item in response.data}
        self.assertEqual(returned_names, {"Main"})

    def test_authorized_folder_access(self):
        """Sprawdza czy wejście do folderu zwraca właściwe metadane i zawartość."""
        SharedFolder.objects.create(folder=self.folder_main, user=self.user_b)
        SharedFolder.objects.create(folder=self.folder_sub, user=self.user_b)

        self.client.force_authenticate(user=self.user_b)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_main.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Sprawdzamy czy w środku jest dokładnie Subfolder
        returned_ids = {str(item["id"]) for item in response.data}
        self.assertIn(str(self.folder_sub.id), returned_ids)

        self.assertNotIn(str(self.quiz_root.id), returned_ids)

    def test_unauthorized_folder_access(self):
        """Bez zmian, status code 403 jest tu wystarczający."""
        self.client.force_authenticate(user=self.user_b)
        url = reverse("library-folder", kwargs={"folder_id": self.folder_main.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
