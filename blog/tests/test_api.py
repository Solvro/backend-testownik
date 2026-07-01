from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from blog.models import BlogPost

User = get_user_model()


class BlogPostAPITestCase(APITestCase):
    """End-to-end tests for the public blog endpoints."""

    LIST_URL = "/api/blog/posts/"

    def setUp(self):
        self.author = User.objects.create_user(
            email="author@example.com", password="pass12345", first_name="Ada", last_name="Lovelace"
        )

        now = timezone.now()
        self.published = BlogPost.objects.create(
            title="Published post",
            slug="published-post",
            content="# Hello\n\nfull body",
            excerpt="short summary",
            author=self.author,
            is_published=True,
            published_at=now - timedelta(days=1),
        )
        self.draft = BlogPost.objects.create(
            title="Draft post",
            slug="draft-post",
            content="draft body",
            is_published=False,
        )
        self.scheduled = BlogPost.objects.create(
            title="Scheduled post",
            slug="scheduled-post",
            content="future body",
            is_published=True,
            published_at=now + timedelta(days=3),
        )

    def _results(self, response):
        return response.data["results"] if isinstance(response.data, dict) else response.data

    # --- Public access -----------------------------------------------------

    def test_list_is_public(self):
        response = self.client.get(self.LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_returns_only_published_and_not_scheduled(self):
        response = self.client.get(self.LIST_URL)
        slugs = {item["slug"] for item in self._results(response)}
        self.assertEqual(slugs, {"published-post"})
        self.assertNotIn("draft-post", slugs)
        self.assertNotIn("scheduled-post", slugs)

    def test_list_uses_list_serializer_without_content(self):
        response = self.client.get(self.LIST_URL)
        item = self._results(response)[0]
        self.assertNotIn("content", item)
        self.assertEqual(item["author_name"], "Ada Lovelace")
        self.assertIn("excerpt", item)

    # --- Detail ------------------------------------------------------------

    def test_retrieve_published_by_slug_includes_content(self):
        response = self.client.get(f"{self.LIST_URL}{self.published.slug}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["slug"], "published-post")
        self.assertIn("content", response.data)
        self.assertIn("created_at", response.data)

    def test_retrieve_draft_returns_404(self):
        response = self.client.get(f"{self.LIST_URL}{self.draft.slug}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_scheduled_returns_404(self):
        response = self.client.get(f"{self.LIST_URL}{self.scheduled.slug}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- recent filter -----------------------------------------------------

    def test_recent_filters_out_older_posts(self):
        BlogPost.objects.create(
            title="Old post",
            slug="old-post",
            content="x",
            is_published=True,
            published_at=timezone.now() - timedelta(days=30),
        )
        response = self.client.get(f"{self.LIST_URL}?recent=7")
        slugs = {item["slug"] for item in self._results(response)}
        self.assertIn("published-post", slugs)
        self.assertNotIn("old-post", slugs)

    def test_recent_invalid_returns_400(self):
        response = self.client.get(f"{self.LIST_URL}?recent=abc")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_recent_non_positive_returns_400(self):
        response = self.client.get(f"{self.LIST_URL}?recent=0")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
