from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.views.decorators.http import require_POST
from unfold.admin import ModelAdmin
from unfold.decorators import action
from unfold.enums import ActionVariant

from blog.widgets import MarkdownEditorWidget

from .diff import diff_texts
from .models import NOTICE_FLAGS, LegalAcceptance, LegalDocumentKind, LegalDocumentStatus, LegalDocumentVersion

FRONTEND_PATHS = {LegalDocumentKind.TERMS: "terms", LegalDocumentKind.PRIVACY: "privacy-policy"}
EXCERPT_LINES = 8


@admin.register(LegalDocumentVersion)
class LegalDocumentVersionAdmin(ModelAdmin):
    list_display = ["__str__", "status", "effective_from", "requires_acceptance", "notify_users", "confirmation_count"]
    list_filter = ["kind", "status", "requires_acceptance", "notify_users"]
    search_fields = ["content"]
    actions_detail = ["publish", "copy_as_draft", "open_in_app"]
    change_form_after_template = "admin/legal/document_version.html"

    class Media:
        # Shares the blog editor's preview styles and its Markdown libraries, but has its own editor.
        css = {"all": ["blog/admin/markdown_editor.css"]}
        js = [*MarkdownEditorWidget.Media.js[:2], "legal/admin/document_editor.js"]

    def get_urls(self):
        diff_preview = self.admin_site.admin_view(require_POST(self.diff_preview))
        return [
            path("diff-preview/", diff_preview, name="legal_legaldocumentversion_diff_preview"),
            *super().get_urls(),
        ]

    def get_fields(self, request, obj=None):
        if obj is not None and obj.is_published:
            # The text is shown below the form, side by side with its rendered version.
            notice = NOTICE_FLAGS[obj.kind]
            return ["kind", notice, "effective_from", "status", "version", "published_at", "created_by"]
        return [
            "kind",
            "content",
            "requires_acceptance",
            "notify_users",
            "effective_from",
            "status",
            "version",
            "created_by",
        ]

    def get_form(self, request, obj=None, **kwargs):
        kwargs["widgets"] = {"content": forms.Textarea(attrs={"class": "blog-markdown-editor", "rows": 20})}
        return super().get_form(request, obj, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        frozen = ["status", "version", "published_at", "created_by"]
        if obj is not None and obj.is_published:
            return [*frozen, "kind", "requires_acceptance", "notify_users", "effective_from"]
        return frozen

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or not obj.is_published)

    def has_publish_permission(self, request, object_id=None):
        if not self.has_change_permission(request):
            return False
        return (
            object_id is not None
            and LegalDocumentVersion.objects.filter(pk=object_id, status=LegalDocumentStatus.DRAFT).exists()
        )

    def has_open_in_app_permission(self, request, object_id=None):
        return object_id is not None and LegalDocumentVersion.objects.published().filter(pk=object_id).exists()

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("acceptances")

    @admin.display(description="Confirmations")
    def confirmation_count(self, obj):
        return obj.acceptances.count() if getattr(obj, NOTICE_FLAGS[obj.kind]) else "–"

    def add_view(self, request, form_url="", extra_context=None):
        extra_context = {**(extra_context or {}), "legal_diff_url": self._diff_preview_url()}
        return super().add_view(request, form_url, extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        document = self.get_object(request, object_id)
        if document is not None:
            extra_context = {
                **(extra_context or {}),
                **self._diff_context(document.kind, document.content, request.GET.get("compare"), document.version),
                "legal_diff_url": None if document.is_published else self._diff_preview_url(),
                "legal_excerpt": "\n".join(document.content.splitlines()[:EXCERPT_LINES]),
                "legal_is_truncated": len(document.content.splitlines()) > EXCERPT_LINES,
            }
        return super().change_view(request, object_id, form_url, extra_context)

    def diff_preview(self, request):
        """The comparison for text still being edited. Nothing is saved."""
        if not (self.has_add_permission(request) or self.has_change_permission(request)):
            raise PermissionDenied
        context = self._diff_context(
            request.POST.get("kind", ""), request.POST.get("content", ""), request.POST.get("compare")
        )
        return render(request, "admin/legal/document_diff.html", context)

    @staticmethod
    def _diff_preview_url():
        return reverse("admin:legal_legaldocumentversion_diff_preview")

    @staticmethod
    def _diff_context(kind, content, compare=None, version=None):
        """Compare with the chosen version, else the previous one (or the latest one, for a draft)."""
        if kind not in LegalDocumentKind.values:
            return {}
        choices = list(LegalDocumentVersion.objects.published().filter(kind=kind).order_by("-version"))
        choices = [choice for choice in choices if choice.version != version]
        if not choices:
            return {"legal_diff_none": True}
        older = [choice for choice in choices if version is None or choice.version < version]
        base = next(
            (choice for choice in choices if str(choice.version) == compare),
            older[0] if older else choices[0],
        )
        return {
            "legal_diff": diff_texts(base.content, content),
            "legal_diff_base": base,
            "legal_diff_choices": choices,
        }

    @action(description="Publish", icon="publish", variant=ActionVariant.PRIMARY, permissions=["publish"])
    def publish(self, request, object_id):
        document = get_object_or_404(LegalDocumentVersion, pk=object_id)
        try:
            document.publish()
        except ValidationError as error:
            self.message_user(request, " ".join(error.messages), messages.ERROR)
        else:
            self.message_user(
                request,
                f"Published {document}, in force from {document.effective_from:%d.%m.%Y %H:%M}.",
                messages.SUCCESS,
            )
        return redirect(reverse("admin:legal_legaldocumentversion_change", args=[object_id]))

    @action(description="Copy as draft", icon="content_copy")
    def copy_as_draft(self, request, object_id):
        source = get_object_or_404(LegalDocumentVersion, pk=object_id)
        draft = LegalDocumentVersion.objects.create(kind=source.kind, content=source.content, created_by=request.user)
        self.message_user(request, f"Created a draft from {source}.", messages.SUCCESS)
        return redirect(reverse("admin:legal_legaldocumentversion_change", args=[draft.pk]))

    @action(
        description="Open in app",
        icon="open_in_new",
        attrs={"target": "_blank", "rel": "noopener noreferrer"},
        permissions=["open_in_app"],
    )
    def open_in_app(self, request, object_id):
        document = get_object_or_404(LegalDocumentVersion.objects.published(), pk=object_id)
        frontend_url = settings.FRONTEND_URL.rstrip("/")
        return redirect(f"{frontend_url}/{FRONTEND_PATHS[document.kind]}/v/{document.version}")


@admin.register(LegalAcceptance)
class LegalAcceptanceAdmin(ModelAdmin):
    list_display = ["user", "version", "accepted_at"]
    list_filter = ["version"]
    search_fields = ["user__email", "user__first_name", "user__last_name"]
    readonly_fields = ["user", "version", "accepted_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
