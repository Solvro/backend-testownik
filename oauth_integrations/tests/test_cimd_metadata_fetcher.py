from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from oauth2_provider.cimd import resolve_cimd_application
from oauth2_provider.models import get_application_model

from oauth_integrations.models import OAuthClientMetadata

CLIENT_ID = "https://example.com/client.json"


def _document(**overrides):
    return {
        "client_id": CLIENT_ID,
        "client_name": "Native Client",
        "client_uri": "https://example.com",
        "logo_uri": "https://example.com/logo.png",
        "redirect_uris": ["https://example.com/callback"],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        **overrides,
    }


@patch("oauth_integrations.cimd_metadata_fetcher.SafeMetadataFetcher.fetch")
class PersistingCIMDMetadataFetcherTests(TestCase):
    def setUp(self):
        cache.clear()

    def _resolve(self):
        return resolve_cimd_application(CLIENT_ID, request=None)

    def _expire(self, application):
        application.cimd_expires_at = timezone.now() - timedelta(seconds=1)
        application.save(update_fields=["cimd_expires_at"])
        cache.clear()

    def test_accepted_document_persists_display_metadata_linked_to_application(self, fetch):
        fetch.return_value = (_document(), 3600)

        application = self._resolve()

        self.assertIsNotNone(application)
        metadata = OAuthClientMetadata.objects.get(client_id_url=CLIENT_ID)
        self.assertEqual(metadata.application, application)
        self.assertEqual(metadata.client_name, "Native Client")
        self.assertEqual(metadata.client_uri, "https://example.com")
        self.assertEqual(metadata.logo_uri, "https://example.com/logo.png")
        self.assertAlmostEqual(metadata.cache_expires_at.timestamp(), application.cimd_expires_at.timestamp(), delta=5)

    def test_rejected_document_persists_nothing(self, fetch):
        fetch.return_value = (_document(client_id="https://evil.example.com/client.json"), 3600)

        self.assertIsNone(self._resolve())

        self.assertFalse(OAuthClientMetadata.objects.exists())
        self.assertFalse(get_application_model().objects.filter(client_id=CLIENT_ID).exists())

    def test_accepted_refresh_updates_existing_metadata(self, fetch):
        fetch.return_value = (_document(), 3600)
        application = self._resolve()
        self._expire(application)
        fetch.return_value = (_document(client_uri="https://updated.example.com"), 3600)

        refreshed = self._resolve()

        self.assertEqual(refreshed.pk, application.pk)
        self.assertEqual(OAuthClientMetadata.objects.count(), 1)
        self.assertEqual(OAuthClientMetadata.objects.get().client_uri, "https://updated.example.com")

    def test_rejected_refresh_keeps_previous_display_metadata(self, fetch):
        fetch.return_value = (_document(), 3600)
        application = self._resolve()
        self._expire(application)
        fetch.return_value = (
            _document(client_uri="https://attacker.example.com", grant_types=["client_credentials"]),
            3600,
        )

        self.assertIsNone(self._resolve())

        metadata = OAuthClientMetadata.objects.get()
        self.assertEqual(metadata.client_uri, "https://example.com")
        self.assertEqual(metadata.logo_uri, "https://example.com/logo.png")

    def test_unrelated_save_after_rejected_refresh_does_not_persist_rejected_document(self, fetch):
        fetch.return_value = (_document(), 3600)
        application = self._resolve()
        self._expire(application)
        fetch.return_value = (
            _document(client_uri="https://attacker.example.com", grant_types=["client_credentials"]),
            3600,
        )
        self.assertIsNone(self._resolve())

        application.refresh_from_db()
        application.name = "Renamed in admin"
        application.save()

        self.assertEqual(OAuthClientMetadata.objects.get().client_uri, "https://example.com")

    def test_invalid_display_urls_are_dropped(self, fetch):
        fetch.return_value = (_document(client_uri="javascript:alert(1)", logo_uri=["not", "a", "url"]), 3600)

        self.assertIsNotNone(self._resolve())

        metadata = OAuthClientMetadata.objects.get()
        self.assertEqual(metadata.client_uri, "")
        self.assertEqual(metadata.logo_uri, "")
