from rest_framework import status
from rest_framework.test import APITestCase
from users.models import User
from quizzes.models import Folder, Quiz
from django.urls import reverse


class QuizArchiveTests(APITestCase):
    def setUp(self):
        self.user = User(email='quiz_archive_test@example.com', first_name='Test', last_name='User')
        self.user.set_password('password')
        self.user.save()
        self.client.force_authenticate(user=self.user)
        self.quiz = Quiz.objects.create(
            title="Test Quiz",
            maintainer=self.user
        )

    def test_archive_quiz_success(self):
        url = reverse('quiz-move-to-archive', args=[self.quiz.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.folder.folder_type, Folder.Type.ARCHIVE)

    def test_move_quiz_from_regular_folder_to_archive(self):
        regular_folder = Folder.objects.create(name="Regular", owner=self.user)
        self.quiz.folder = regular_folder
        self.quiz.save()

        url = reverse('quiz-move-to-archive', args=[self.quiz.id])
        response = self.client.post(url)

        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.folder.folder_type, Folder.Type.ARCHIVE)

    def test_archive_missing_folder_handling(self):
        Folder.objects.filter(owner=self.user, folder_type=Folder.Type.ARCHIVE).delete()

        url = reverse('quiz-move-to-archive', args=[self.quiz.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
