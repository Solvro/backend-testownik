"""Guest-owned quizzes are private to the guest whatever their visibility (#231)."""

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Comment, Quiz, QuizSession
from quizzes.permissions import user_has_quiz_read_access
from quizzes.services.operations import searchable_quizzes_queryset
from users.models import AccountType, User
from users.services import migrate_guest_to_user


@override_settings(INTERNAL_API_KEY="test-api-key")
class GuestQuizPrivacyTests(APITestCase):
    def setUp(self):
        self.guest = User.objects.create_guest_user()
        self.student = User.objects.create(
            email="student@example.com",
            first_name="Student",
            last_name="User",
            account_type=AccountType.STUDENT,
        )
        self.guest_quiz = Quiz.objects.create(
            title="Guest public quiz",
            creator=self.guest,
            folder=self.guest.root_folder,
            visibility=3,
            allow_anonymous=True,
        )

    def test_owner_guest_can_read_own_quiz(self):
        self.assertTrue(user_has_quiz_read_access(self.guest, self.guest_quiz))
        self.client.force_authenticate(user=self.guest)
        response = self.client.get(reverse("quiz-detail", kwargs={"pk": self.guest_quiz.id}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_other_user_cannot_read_guest_quiz(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(reverse("quiz-detail", kwargs={"pk": self.guest_quiz.id}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_cannot_read_guest_quiz(self):
        response = self.client.get(reverse("quiz-metadata", kwargs={"pk": self.guest_quiz.id}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_internal_metadata_hides_guest_quiz_from_others(self):
        url = reverse("quiz-metadata", kwargs={"pk": self.guest_quiz.id})
        self.assertEqual(self.client.get(url, HTTP_API_KEY="test-api-key").status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=self.guest)
        self.assertEqual(self.client.get(url, HTTP_API_KEY="test-api-key").status_code, status.HTTP_200_OK)

    def test_search_excludes_guest_quiz(self):
        self.client.force_authenticate(user=self.student)
        response = self.client.get(reverse("search-quizzes"), {"query": "Guest"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["public_quizzes"], [])
        self.assertFalse(searchable_quizzes_queryset(self.student, "Guest").exists())
        self.assertTrue(searchable_quizzes_queryset(self.guest, "Guest").exists())

    def test_last_used_excludes_guest_quiz_for_others(self):
        QuizSession.objects.create(quiz=self.guest_quiz, user=self.student)
        self.client.force_authenticate(user=self.student)
        response = self.client.get(reverse("last-used-quizzes"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"] if isinstance(response.data, dict) else response.data
        self.assertEqual(results, [])

    def test_comments_on_guest_quiz_are_hidden_from_others(self):
        Comment.objects.create(quiz=self.guest_quiz, author=self.guest, content="Guest note")
        self.client.force_authenticate(user=self.student)
        response = self.client.get(reverse("comment-list"), {"quiz": str(self.guest_quiz.id)})
        results = response.data["results"] if isinstance(response.data, dict) else response.data
        self.assertEqual(list(results), [])

    def test_quiz_becomes_visible_after_guest_signs_up(self):
        user = User.objects.create(email="converted@example.com", first_name="Converted", last_name="User")
        self.assertTrue(migrate_guest_to_user(str(self.guest.id), user))
        self.guest_quiz.refresh_from_db()
        self.assertTrue(user_has_quiz_read_access(self.student, self.guest_quiz))
