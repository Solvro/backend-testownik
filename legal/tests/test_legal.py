from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from legal.models import (
    TERMS_NOTICE_PERIOD,
    LegalAcceptance,
    LegalDocumentKind,
    LegalDocumentStatus,
    LegalDocumentVersion,
    pending_version_for,
)

User = get_user_model()
TERMS = LegalDocumentKind.TERMS
PRIVACY = LegalDocumentKind.PRIVACY


def published(kind=TERMS, *, days_from_now=0, requires_acceptance=False, notify_users=False, content="Treść"):
    document = LegalDocumentVersion.objects.create(
        kind=kind,
        content=content,
        requires_acceptance=requires_acceptance,
        notify_users=notify_users,
        effective_from=timezone.now() + timedelta(days=days_from_now) if days_from_now > 0 else None,
    )
    document.publish()
    if days_from_now < 0:
        document.effective_from = timezone.now() + timedelta(days=days_from_now)
        document.save(update_fields=["effective_from"])
    return document


class PublishTestCase(TestCase):
    def setUp(self):
        LegalDocumentVersion.objects.all().delete()

    def test_publish_numbers_versions_per_kind(self):
        self.assertEqual(published(TERMS).version, 1)
        self.assertEqual(published(TERMS).version, 2)
        self.assertEqual(published(PRIVACY).version, 1)

    def test_terms_needing_acceptance_default_to_the_notice_period(self):
        before = timezone.now()
        document = published(TERMS, requires_acceptance=True)
        self.assertGreaterEqual(document.effective_from, before + TERMS_NOTICE_PERIOD)

    def test_other_versions_apply_immediately(self):
        document = published(PRIVACY)
        self.assertLessEqual(document.effective_from, timezone.now())

    def test_past_start_date_is_rejected(self):
        draft = LegalDocumentVersion.objects.create(
            kind=TERMS, content="x", effective_from=timezone.now() - timedelta(days=1)
        )
        with self.assertRaises(ValidationError):
            draft.publish()

    def test_publishing_twice_is_rejected(self):
        document = published()
        with self.assertRaises(ValidationError):
            document.publish()


class PendingAcceptanceTestCase(TestCase):
    def setUp(self):
        LegalDocumentVersion.objects.all().delete()
        self.user = User.objects.create_user(email="user@example.com")
        User.objects.filter(pk=self.user.pk).update(created_at=timezone.now() - timedelta(days=30))
        self.user.refresh_from_db()

    def test_existing_user_must_confirm_new_terms(self):
        document = published(requires_acceptance=True)
        self.assertEqual(pending_version_for(self.user, TERMS), document)

    def test_announced_terms_are_pending_before_they_apply(self):
        document = published(requires_acceptance=True, days_from_now=14)
        self.assertEqual(pending_version_for(self.user, TERMS), document)

    def test_only_the_newest_version_counts(self):
        published(requires_acceptance=True, days_from_now=-5)
        newest = published(requires_acceptance=True)
        self.assertEqual(pending_version_for(self.user, TERMS), newest)

    def test_versions_without_acceptance_are_not_pending(self):
        published()
        self.assertIsNone(pending_version_for(self.user, TERMS))

    def test_users_who_joined_later_are_not_asked(self):
        published(requires_acceptance=True, days_from_now=-40)
        self.assertIsNone(pending_version_for(self.user, TERMS))

    def test_accepted_version_is_not_pending(self):
        document = published(requires_acceptance=True)
        LegalAcceptance.objects.create(user=self.user, version=document)
        self.assertIsNone(pending_version_for(self.user, TERMS))

    def test_guests_are_never_asked(self):
        guest = User.objects.create_guest_user()
        User.objects.filter(pk=guest.pk).update(created_at=timezone.now() - timedelta(days=30))
        guest.refresh_from_db()
        published(requires_acceptance=True)
        self.assertIsNone(pending_version_for(guest, TERMS))

    def test_flagged_privacy_update_is_pending(self):
        document = published(PRIVACY, notify_users=True)
        self.assertEqual(pending_version_for(self.user, PRIVACY), document)

    def test_privacy_update_without_a_notice_is_not_pending(self):
        published(PRIVACY)
        self.assertIsNone(pending_version_for(self.user, PRIVACY))

    def test_closed_privacy_notice_is_not_pending(self):
        document = published(PRIVACY, notify_users=True)
        LegalAcceptance.objects.create(user=self.user, version=document)
        self.assertIsNone(pending_version_for(self.user, PRIVACY))

    def test_users_who_joined_after_a_privacy_update_are_not_notified(self):
        published(PRIVACY, notify_users=True, days_from_now=-40)
        self.assertIsNone(pending_version_for(self.user, PRIVACY))


class NoticeOptionTestCase(TestCase):
    def test_only_terms_can_require_acceptance(self):
        document = LegalDocumentVersion(kind=PRIVACY, content="Treść", requires_acceptance=True)
        with self.assertRaises(ValidationError) as caught:
            document.clean()
        self.assertIn("requires_acceptance", caught.exception.message_dict)

    def test_only_privacy_updates_can_notify_users(self):
        document = LegalDocumentVersion(kind=TERMS, content="Treść", notify_users=True)
        with self.assertRaises(ValidationError) as caught:
            document.clean()
        self.assertIn("notify_users", caught.exception.message_dict)


class LegalApiTestCase(APITestCase):
    def setUp(self):
        LegalDocumentVersion.objects.all().delete()
        self.user = User.objects.create_user(email="user@example.com")
        User.objects.filter(pk=self.user.pk).update(created_at=timezone.now() - timedelta(days=30))
        self.user.refresh_from_db()

    def test_document_returns_current_and_upcoming(self):
        current = published(content="stara")
        upcoming = published(days_from_now=14)
        LegalDocumentVersion.objects.create(kind=TERMS, content="szkic")

        response = self.client.get("/api/legal/terms/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["current"]["id"], str(current.id))
        self.assertEqual(response.data["current"]["content"], "stara")
        self.assertEqual(response.data["upcoming"]["version"], upcoming.version)
        self.assertNotIn("content", response.data["upcoming"])

    def test_document_without_versions_is_empty(self):
        response = self.client.get("/api/legal/privacy/")
        self.assertEqual(response.data, {"current": None, "upcoming": None})

    def test_unknown_kind_is_404(self):
        self.assertEqual(self.client.get("/api/legal/cookies/").status_code, status.HTTP_404_NOT_FOUND)

    def test_archive_lists_published_versions_only(self):
        published()
        published()
        LegalDocumentVersion.objects.create(kind=TERMS, content="szkic")

        response = self.client.get("/api/legal/terms/versions/")

        self.assertEqual([v["version"] for v in response.data], [2, 1])

    def test_version_detail(self):
        published(content="pierwsza")
        response = self.client.get("/api/legal/terms/versions/1/")
        self.assertEqual(response.data["content"], "pierwsza")
        self.assertEqual(self.client.get("/api/legal/terms/versions/9/").status_code, status.HTTP_404_NOT_FOUND)

    def test_pending_requires_login(self):
        self.assertEqual(self.client.get("/api/legal/pending/").status_code, status.HTTP_401_UNAUTHORIZED)

    def test_pending_and_accept(self):
        document = published(requires_acceptance=True)
        self.client.force_authenticate(self.user)

        pending = self.client.get("/api/legal/pending/").data
        self.assertEqual(pending["terms"]["id"], str(document.id))
        self.assertIsNone(pending["privacy"])

        for _ in range(2):
            response = self.client.post("/api/legal/acceptances/", {"versions": [str(document.id)]}, format="json")
            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertIsNone(self.client.get("/api/legal/pending/").data["terms"])
        self.assertEqual(LegalAcceptance.objects.filter(user=self.user).count(), 1)

    def test_both_documents_are_confirmed_together(self):
        terms = published(requires_acceptance=True)
        privacy = published(PRIVACY, notify_users=True)
        self.client.force_authenticate(self.user)

        pending = self.client.get("/api/legal/pending/").data
        self.assertEqual((pending["terms"]["id"], pending["privacy"]["id"]), (str(terms.id), str(privacy.id)))

        response = self.client.post(
            "/api/legal/acceptances/", {"versions": [str(terms.id), str(privacy.id)]}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get("/api/legal/pending/").data, {"terms": None, "privacy": None})

    def test_drafts_cannot_be_accepted(self):
        draft = LegalDocumentVersion.objects.create(kind=TERMS, content="szkic", status=LegalDocumentStatus.DRAFT)
        self.client.force_authenticate(self.user)
        response = self.client.post("/api/legal/acceptances/", {"versions": [str(draft.id)]}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
