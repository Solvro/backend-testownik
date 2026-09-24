from django import forms


class MarkdownEditorWidget(forms.Textarea):
    """
    Textarea with a live Markdown preview pane in the admin.

    The heavy lifting happens client-side: `markdown_editor.js` finds textareas
    carrying the `blog-markdown-editor` class, splits the field into an editor
    and a preview pane, and re-renders the preview (via marked.js) on every
    keystroke. marked.js is loaded from a CDN; no server-side rendering or
    Python dependency is involved.

    marked does not strip HTML embedded in the Markdown source, so its output is
    run through DOMPurify before it reaches the preview pane — otherwise a post
    saved by one staff author could execute script in another's admin session.
    Both libraries must load before `markdown_editor.js`, which falls back to
    plain text when either is missing.
    """

    class Media:
        css = {"all": ["blog/admin/markdown_editor.css"]}
        js = [
            "https://cdn.jsdelivr.net/npm/marked@12/marked.min.js",
            "https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js",
            "blog/admin/markdown_editor.js",
        ]

    def __init__(self, attrs=None):
        default_attrs = {"class": "blog-markdown-editor", "rows": 20}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)
