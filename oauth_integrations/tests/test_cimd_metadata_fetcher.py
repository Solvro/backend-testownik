from unittest.mock import patch

from django.test import TestCase

from oauth_integrations.cimd_metadata_fetcher import PersistingCIMDMetadataFetcher
from oauth_integrations.models import OAuthClientMetadata


class PersistingCIMDMetadataFetcherTests(TestCase):
    @patch("oauth_integrations.cimd_metadata_fetcher.SafeMetadataFetcher.fetch")
    def test_fetch_persists_display_metadata_and_refreshes_existing_record(self, fetch):
        client_id = "https://example.com/client.json"
        fetch.return_value = (
            {
                "client_id": client_id,
                "client_name": "Native Client",
                "client_uri": "https://example.com",
                "logo_uri": "https://example.com/logo.png",
                "redirect_uris": ["https://example.com/callback"],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            3600,
        )

        result = PersistingCIMDMetadataFetcher().fetch(client_id)

        self.assertEqual(result, fetch.return_value)
        metadata = OAuthClientMetadata.objects.get(client_id_url=client_id)
        self.assertIsNone(metadata.application)
        self.assertEqual(metadata.client_uri, "https://example.com")
        self.assertEqual(metadata.logo_uri, "https://example.com/logo.png")

        fetch.return_value[0]["client_uri"] = "https://updated.example.com"
        PersistingCIMDMetadataFetcher().fetch(client_id)
        metadata.refresh_from_db()
        self.assertEqual(metadata.client_uri, "https://updated.example.com")
