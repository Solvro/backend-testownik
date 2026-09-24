import re
from pathlib import Path

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

import blog
from blog.admin import BlogPostAdmin
from blog.models import BlogPost
from blog.widgets import MarkdownEditorWidget

User = get_user_model()

EDITOR_JS = Path(blog.__file__).resolve().parent / "static" / "blog" / "admin" / "markdown_editor.js"


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


class MarkdownEditorSanitizerTestCase(SimpleTestCase):
    """
    The preview pane renders post content authored by other staff members, so the
    sanitizer must stay wired up — without it, saved Markdown containing raw HTML
    runs as script in the reviewer's admin session.
    """

    def test_media_loads_sanitizer_before_the_editor_script(self):
        scripts = list(MarkdownEditorWidget.Media.js)
        sanitizer = [path for path in scripts if "purify" in path.lower()]
        self.assertTrue(sanitizer, f"no DOMPurify bundle in widget media: {scripts}")
        self.assertLess(scripts.index(sanitizer[0]), scripts.index("blog/admin/markdown_editor.js"))

    def test_every_innerhtml_assignment_goes_through_the_sanitizer(self):
        source = EDITOR_JS.read_text(encoding="utf-8")
        assignments = re.findall(r"^.*\.innerHTML\s*=.*$", source, flags=re.MULTILINE)
        self.assertTrue(assignments, "expected the preview pane to assign innerHTML")
        for line in assignments:
            self.assertIn("DOMPurify.sanitize", line.strip(), f"unsanitized innerHTML assignment: {line.strip()}")
