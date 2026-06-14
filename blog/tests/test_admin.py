from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from blog.admin import BlogPostAdmin
from blog.models import BlogPost

User = get_user_model()


class BlogPostAdminTestCase(TestCase):
    """Tests for the admin-side publishing behaviour."""

    def setUp(self):
        self.admin = BlogPostAdmin(BlogPost, AdminSite())
        self.staff = User.objects.create_user(email="staff@example.com", password="pass12345", is_staff=True)
        self.request = RequestFactory().post("/admin/blog/blogpost/add/")
        self.request.user = self.staff

    def _save(self, post, change=False):
        self.admin.save_model(self.request, post, form=None, change=change)

    def test_published_at_is_stamped_on_first_publish(self):
        post = BlogPost(title="T", slug="t", content="x", is_published=True)
        self._save(post)
        self.assertIsNotNone(post.published_at)

    def test_published_at_not_overwritten_when_already_set(self):
        post = BlogPost(title="T", slug="t", content="x", is_published=True)
        self._save(post)
        original = post.published_at

        post.title = "T2"
        self._save(post, change=True)
        self.assertEqual(post.published_at, original)

    def test_draft_has_no_published_at(self):
        post = BlogPost(title="Draft", slug="draft", content="x", is_published=False)
        self._save(post)
        self.assertIsNone(post.published_at)

    def test_author_defaults_to_editing_user(self):
        post = BlogPost(title="T", slug="t", content="x", is_published=False)
        self._save(post)
        self.assertEqual(post.author, self.staff)
