from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from legal.models import LegalDocumentKind, LegalDocumentStatus, LegalDocumentVersion

User = get_user_model()


class LegalAdminTestCase(TestCase):
    def setUp(self):
        LegalDocumentVersion.objects.all().delete()
        self.staff = User.objects.create_superuser(email="admin@example.com", password="pass12345")
        self.client.force_login(self.staff)

    def _change_url(self, document):
        return reverse("admin:legal_legaldocumentversion_change", args=[document.pk])

    def test_publish_action(self):
        draft = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="v1")

        response = self.client.get(reverse("admin:legal_legaldocumentversion_publish", args=[draft.pk]))

        self.assertRedirects(response, self._change_url(draft), fetch_redirect_response=False)
        draft.refresh_from_db()
        self.assertEqual((draft.status, draft.version), (LegalDocumentStatus.PUBLISHED, 1))

    def test_published_version_is_read_only(self):
        document = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="v1")
        document.publish()

        self.client.post(self._change_url(document), {"kind": "terms", "content": "zmienione"})

        document.refresh_from_db()
        self.assertEqual(document.content, "v1")

    def test_copy_as_draft_and_diff(self):
        document = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="linia\nstara")
        document.publish()

        response = self.client.get(reverse("admin:legal_legaldocumentversion_copy_as_draft", args=[document.pk]))

        draft = LegalDocumentVersion.objects.exclude(pk=document.pk).get()
        self.assertRedirects(response, self._change_url(draft), fetch_redirect_response=False)
        self.assertEqual((draft.status, draft.content), (LegalDocumentStatus.DRAFT, document.content))

        draft.content = "linia\nnowa"
        draft.save()
        page = self.client.get(self._change_url(draft))
        self.assertContains(page, "<ins>nowa</ins>", html=False)
        self.assertContains(page, "<del>stara</del>", html=False)
        self.assertContains(page, "Compared with <strong>Terms of service v1</strong>", html=False)

    def test_compare_with_a_chosen_version(self):
        first = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="jeden")
        first.publish()
        second = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="dwa")
        second.publish()
        draft = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="trzy")

        page = self.client.get(self._change_url(draft) + "?compare=1")

        self.assertContains(page, "Compared with <strong>Terms of service v1</strong>", html=False)
        self.assertContains(page, "<del>jeden</del>", html=False)

    def test_first_version_has_nothing_to_compare(self):
        document = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="v1")
        document.publish()
        self.assertContains(self.client.get(self._change_url(document)), "nothing to compare it with")

    def test_published_version_shows_an_excerpt_and_the_full_text(self):
        lines = [f"Linia {n}" for n in range(20)]
        document = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="\n".join(lines))
        document.publish()

        page = self.client.get(self._change_url(document)).content.decode()

        excerpt = page.split("data-legal-excerpt>")[1].split("</pre>")[0]
        self.assertIn("Linia 7", excerpt)
        self.assertNotIn("Linia 8", excerpt)
        self.assertIn("Linia 19", page.split("data-legal-source>")[1].split("</pre>")[0])
        self.assertIn("Show full content", page)
        self.assertNotIn('name="content"', page)

    def test_draft_is_edited_in_the_markdown_editor(self):
        draft = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="v1")
        page = self.client.get(self._change_url(draft))
        self.assertContains(page, "blog-markdown-editor")
        self.assertNotContains(page, "data-legal-excerpt")

    def _diff_preview(self, **data):
        return self.client.post(reverse("admin:legal_legaldocumentversion_diff_preview"), data)

    def test_diff_preview_compares_unsaved_text_without_saving_it(self):
        LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="linia\nstara").publish()
        draft = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="linia\nstara")

        response = self._diff_preview(kind="terms", content="linia\nnowa")

        self.assertContains(response, "<ins>nowa</ins>", html=False)
        self.assertContains(response, "<del>stara</del>", html=False)
        draft.refresh_from_db()
        self.assertEqual(draft.content, "linia\nstara")

    def test_diff_preview_escapes_the_text(self):
        LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="tekst").publish()

        response = self._diff_preview(kind="terms", content="<script>alert(1)</script>")

        self.assertNotContains(response, "<script>alert(1)", html=False)

    def test_diff_preview_uses_the_chosen_version(self):
        for content in ("jeden", "dwa"):
            LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content=content).publish()

        response = self._diff_preview(kind="terms", content="trzy", compare="1")

        self.assertContains(response, "Compared with <strong>Terms of service v1</strong>", html=False)
        self.assertContains(response, 'data-compare="2"', html=False)

    def test_diff_preview_without_a_document_type(self):
        self.assertContains(self._diff_preview(kind="", content="tekst"), "Choose a document type")

    def test_diff_preview_needs_a_post_from_staff(self):
        url = reverse("admin:legal_legaldocumentversion_diff_preview")
        self.assertEqual(self.client.get(url).status_code, 405)

        self.client.logout()
        response = self.client.post(url, {"kind": "terms", "content": "tekst"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_only_drafts_refresh_the_comparison(self):
        document = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="v1")
        document.publish()
        draft = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="v2")
        url = reverse("admin:legal_legaldocumentversion_diff_preview")

        self.assertNotContains(self.client.get(self._change_url(document)), f'data-url="{url}"', html=False)
        self.assertContains(self.client.get(self._change_url(draft)), f'data-url="{url}"', html=False)
        add_page = self.client.get(reverse("admin:legal_legaldocumentversion_add"))
        self.assertContains(add_page, f'data-url="{url}"', html=False)
