from django.test import SimpleTestCase

from legal.diff import diff_texts


class DiffTextsTestCase(SimpleTestCase):
    def test_marks_changed_words_on_paired_lines(self):
        diff = diff_texts("a\nKorzystanie jest bezpłatne.\nb", "a\nKorzystanie jest darmowe.\nb")
        self.assertEqual((diff.added, diff.removed), (1, 1))
        self.assertIn("<del>bezpłatne.</del>", diff.html)
        self.assertIn("<ins>darmowe.</ins>", diff.html)

    def test_counts_added_and_removed_lines(self):
        diff = diff_texts("a\nb", "a\nb\nc\nd")
        self.assertEqual((diff.added, diff.removed), (2, 0))
        self.assertIn("ld-add", diff.html)

    def test_collapses_long_unchanged_runs(self):
        old = "\n".join(f"linia {n}" for n in range(20))
        new = old.replace("linia 10", "zmieniona")
        diff = diff_texts(old, new)
        self.assertIn("ld-gap", diff.html)
        self.assertNotIn("linia 3<", diff.html)
        self.assertIn("linia 9", diff.html)

    def test_escapes_html_in_the_text(self):
        diff = diff_texts("<b>stare</b>", "<script>x</script>")
        self.assertNotIn("<script>", diff.html)
        self.assertIn("&lt;script&gt;", diff.html)

    def test_identical_texts(self):
        self.assertTrue(diff_texts("a\nb", "a\nb").is_empty)
