from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from quizzes.models import Folder, Quiz, QuizRating
from users.models import AccountLevel, AccountLevelGrant, AccountLevelGrantSource

User = get_user_model()


class QuizRatingViewSetTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="example_1@mail.com", password="password")
        self.other_user = User.objects.create_user(email="example_2@mail.com", password="password")
        self.folder = Folder.objects.create(name="Test Folder", owner=self.user)
        self.quiz = Quiz.objects.create(title="Test Quiz", creator=self.user, folder=self.folder)
        self.rating = QuizRating.objects.create(user=self.user, quiz=self.quiz, score=4)
        self.client.force_authenticate(user=self.user)

    # LIST
    def test_list_own_ratings(self):
        response = self.client.get("/api/quiz-ratings/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], str(self.rating.id))

    def test_list_ratings_requires_quiz_param(self):
        response = self.client.get("/api/quiz-ratings/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_can_see_other_user_ratings_on_quiz(self):
        QuizRating.objects.create(user=self.other_user, quiz=self.quiz, score=2)
        response = self.client.get(f"/api/quiz-ratings/?quiz={self.quiz.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_rating_list_prefetches_grants_for_all_serialized_users(self):
        raters = [User.objects.create_user(email=f"rater-{index}@example.com") for index in range(5)]
        QuizRating.objects.bulk_create([QuizRating(user=rater, quiz=self.quiz, score=3) for rater in raters])
        starts_at = timezone.now() - timedelta(minutes=1)
        expires_at = timezone.now() + timedelta(days=1)
        AccountLevelGrant.objects.bulk_create(
            [
                AccountLevelGrant(
                    user=rater,
                    level=AccountLevel.SILVER,
                    source=AccountLevelGrantSource.ADMIN,
                    starts_at=starts_at,
                    expires_at=expires_at,
                )
                for rater in raters
            ]
        )

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(f"/api/quiz-ratings/?quiz={self.quiz.id}")

        grant_table_queries = [query for query in queries if "users_accountlevelgrant" in query["sql"].lower()]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), len(raters) + 1)
        self.assertEqual(len(grant_table_queries), 1)
        self.assertTrue(
            all(
                row["user"]["account_level"] == AccountLevel.SILVER
                for row in response.data
                if row["user"]["id"] in {str(rater.pk) for rater in raters}
            )
        )

    # CREATE
    def test_create_rating(self):
        quiz2 = Quiz.objects.create(title="Quiz 2", creator=self.user, folder=self.folder)
        response = self.client.post(
            "/api/quiz-ratings/",
            {
                "quiz": quiz2.id,
                "score": 5,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_rating_invalid_score(self):
        response = self.client.post(
            "/api/quiz-ratings/",
            {
                "quiz": self.quiz.id,
                "score": 6,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_rating_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/quiz-ratings/",
            {
                "quiz": self.quiz.id,
                "score": 3,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # UPDATE
    def test_update_own_rating(self):
        response = self.client.patch(
            f"/api/quiz-ratings/{self.rating.id}/",
            {
                "score": 2,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["score"], 2)

    def test_cannot_update_other_user_rating(self):
        other_rating = QuizRating.objects.create(user=self.other_user, quiz=self.quiz, score=3)
        response = self.client.patch(
            f"/api/quiz-ratings/{other_rating.id}/",
            {
                "score": 1,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # DELETE
    def test_delete_own_rating(self):
        response = self.client.delete(f"/api/quiz-ratings/{self.rating.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_cannot_delete_other_user_rating(self):
        other_rating = QuizRating.objects.create(user=self.other_user, quiz=self.quiz, score=3)
        response = self.client.delete(f"/api/quiz-ratings/{other_rating.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_rate_inaccessible_quiz(self):
        other_folder = Folder.objects.create(name="Other", owner=self.other_user)
        private_quiz = Quiz.objects.create(title="Private", creator=self.other_user, folder=other_folder, visibility=0)
        response = self.client.post(
            "/api/quiz-ratings/",
            {"quiz": private_quiz.id, "score": 5},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(QuizRating.objects.filter(user=self.user, quiz=private_quiz).exists())

    def test_cannot_rate_same_quiz_twice(self):
        response = self.client.post(
            "/api/quiz-ratings/",
            {"quiz": self.quiz.id, "score": 3},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", response.data)
