from django import forms

from .models import BlogPost
from .widgets import MarkdownEditorWidget


class BlogPostAdminForm(forms.ModelForm):
    class Meta:
        model = BlogPost
        fields = ["title", "slug", "content", "excerpt", "author", "is_published", "published_at"]
        widgets = {"content": MarkdownEditorWidget()}
