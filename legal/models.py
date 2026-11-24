import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone

# Terms changes that need acceptance are announced this long before they apply (§14 of the terms).
TERMS_NOTICE_PERIOD = timedelta(days=14)


class LegalDocumentKind(models.TextChoices):
    TERMS = "terms", "Terms of service"
    PRIVACY = "privacy", "Privacy policy"


# The field that puts a published version of each document in the in-app notice.
NOTICE_FLAGS = {LegalDocumentKind.TERMS: "requires_acceptance", LegalDocumentKind.PRIVACY: "notify_users"}


class LegalDocumentStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"


class LegalDocumentVersionQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=LegalDocumentStatus.PUBLISHED)

    def current(self, kind, now=None):
        """The version in force now, or None before the first one applies."""
        now = now or timezone.now()
        return (
            self.published().filter(kind=kind, effective_from__lte=now).order_by("-effective_from", "-version").first()
        )

    def upcoming(self, kind, now=None):
        """The next published version that hasn't applied yet."""
        now = now or timezone.now()
        return self.published().filter(kind=kind, effective_from__gt=now).order_by("effective_from").first()


class LegalDocumentVersion(models.Model):
    """
    One version of the terms or the privacy policy, written in Markdown.

    Drafts can be edited freely. Publishing assigns the next version number and
    freezes the text; a correction is a new version. A published version
    applies from `effective_from`, so it can be announced ahead of time.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16, choices=LegalDocumentKind.choices)
    version = models.PositiveIntegerField(null=True, blank=True, editable=False)
    content = models.TextField(
        help_text="Markdown. A heading can end with an anchor, e.g. `## VIII. Funkcje AI {#funkcje-ai}`.",
    )
    requires_acceptance = models.BooleanField(
        default=False,
        help_text=(
            "Ask signed-in users to confirm this version in a notice. Only for significant changes to the terms; "
            "they then apply after 14 days by default."
        ),
    )
    notify_users = models.BooleanField(
        default=False,
        help_text="Tell signed-in users about this privacy policy update in a notice. They only need to close it.",
    )
    status = models.CharField(max_length=16, choices=LegalDocumentStatus.choices, default=LegalDocumentStatus.DRAFT)
    effective_from = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this version applies. Left empty: on publishing, or 14 days later if it requires acceptance.",
    )
    published_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="legal_document_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LegalDocumentVersionQuerySet.as_manager()

    class Meta:
        ordering = ["kind", "-version", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "version"],
                condition=models.Q(version__isnull=False),
                name="unique_legal_document_version",
            )
        ]
        verbose_name = "legal document version"
        verbose_name_plural = "legal document versions"

    def __str__(self):
        label = f"v{self.version}" if self.version else "draft"
        return f"{self.get_kind_display()} {label}"

    def clean(self):
        super().clean()
        if self.requires_acceptance and self.kind != LegalDocumentKind.TERMS:
            raise ValidationError({"requires_acceptance": "Only the terms can require acceptance."})
        if self.notify_users and self.kind != LegalDocumentKind.PRIVACY:
            raise ValidationError({"notify_users": "Only a privacy policy update can use this notice."})

    @property
    def is_published(self):
        return self.status == LegalDocumentStatus.PUBLISHED

    def publish(self, now=None):
        """Number and freeze this draft; a missing start date follows the notice rules."""
        if self.is_published:
            raise ValidationError("This version is already published.")
        now = now or timezone.now()
        if self.effective_from is None:
            needs_notice = self.kind == LegalDocumentKind.TERMS and self.requires_acceptance
            self.effective_from = now + TERMS_NOTICE_PERIOD if needs_notice else now
        elif self.effective_from < now:
            raise ValidationError("The start date can't be in the past.")
        with transaction.atomic():
            last = (
                LegalDocumentVersion.objects.select_for_update()
                .filter(kind=self.kind, version__isnull=False)
                .aggregate(last=Max("version"))["last"]
            )
            self.version = (last or 0) + 1
            self.status = LegalDocumentStatus.PUBLISHED
            self.published_at = now
            self.save()


class LegalAcceptance(models.Model):
    """A user accepting a terms version, or closing the notice about a privacy policy update."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="legal_acceptances")
    version = models.ForeignKey(LegalDocumentVersion, on_delete=models.PROTECT, related_name="acceptances")
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "version"], name="unique_legal_acceptance")]
        ordering = ["-accepted_at"]
        verbose_name = "legal confirmation"
        verbose_name_plural = "legal confirmations"

    def __str__(self):
        return f"{self.user} → {self.version}"


def record_signup_acceptance(user):
    """Save that a new account accepted the terms in force, as the login page states."""
    current = LegalDocumentVersion.objects.current(LegalDocumentKind.TERMS)
    if current is not None:
        LegalAcceptance.objects.get_or_create(user=user, version=current)


def pending_version_for(user, kind):
    """
    The version of a document this user still has to confirm, if any.

    Only the newest version flagged for a notice counts, and only for users who
    joined before it applied: anyone who joined later agreed to it by signing up.
    Guests never get the notice.
    """
    from users.models import AccountType

    if user.account_type == AccountType.GUEST:
        return None
    latest = (
        LegalDocumentVersion.objects.published()
        .filter(kind=kind, **{NOTICE_FLAGS[kind]: True})
        .order_by("-effective_from", "-version")
        .first()
    )
    if latest is None or latest.effective_from <= user.created_at:
        return None
    if latest.acceptances.filter(user=user).exists():
        return None
    return latest
