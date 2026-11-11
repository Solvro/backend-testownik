from datetime import timedelta
from importlib import import_module

from django.apps import apps
from django.test import TestCase
from django.utils import timezone
from oauth2_provider.models import AbstractApplication, get_application_model

from oauth_integrations.models import OAuthClientMetadata


class CIMDApplicationMigrationTests(TestCase):
    def test_legacy_application_is_marked_for_metadata_refresh(self):
        expires_at = timezone.now() - timedelta(days=1)
        application = get_application_model().objects.create(
            name="Legacy MCP Client",
            client_id="cimd:legacy-id",
            client_type=AbstractApplication.CLIENT_PUBLIC,
            authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
        )
        OAuthClientMetadata.objects.create(
            application=application,
            client_id_url="https://example.com/client.json",
            client_name="MCP Client",
            redirect_uris=["https://example.com/callback"],
            fetched_at=timezone.now() - timedelta(days=2),
            cache_expires_at=expires_at,
        )
        migration = import_module("oauth_integrations.migrations.0003_auto_20260928_1324")
        migration.migrate_cimd_applications(apps, None)

        application.refresh_from_db()
        self.assertEqual(application.client_id, "https://example.com/client.json")
        self.assertEqual(application.registration_source, "cimd")
        self.assertEqual(application.cimd_expires_at, expires_at)

    def test_legacy_application_without_expiry_is_marked_stale(self):
        application = get_application_model().objects.create(
            name="Legacy MCP Client",
            client_id="cimd:legacy-id",
            client_type=AbstractApplication.CLIENT_PUBLIC,
            authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
        )
        OAuthClientMetadata.objects.create(
            application=application,
            client_id_url="https://example.com/client.json",
            client_name="MCP Client",
            redirect_uris=["https://example.com/callback"],
            fetched_at=timezone.now() - timedelta(days=2),
        )
        migration = import_module("oauth_integrations.migrations.0003_auto_20260928_1324")
        migration.migrate_cimd_applications(apps, None)

        application.refresh_from_db()
        self.assertEqual(application.registration_source, "cimd")
        self.assertIsNotNone(application.cimd_expires_at)
        self.assertLessEqual(application.cimd_expires_at, timezone.now())

    def test_long_legacy_url_is_migrated_without_truncation(self):
        client_id_url = f"https://example.com/{'a' * 290}"
        application = get_application_model().objects.create(
            name="Legacy MCP Client",
            client_id="cimd:legacy-id",
            client_type=AbstractApplication.CLIENT_PUBLIC,
            authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
        )
        OAuthClientMetadata.objects.create(
            application=application,
            client_id_url=client_id_url,
            client_name="MCP Client",
            redirect_uris=["https://example.com/callback"],
            fetched_at=timezone.now() - timedelta(days=2),
        )

        migration = import_module("oauth_integrations.migrations.0003_auto_20260928_1324")
        migration.migrate_cimd_applications(apps, None)

        application.refresh_from_db()
        self.assertEqual(application.client_id, client_id_url)
        client_id_field = get_application_model()._meta.get_field("client_id")
        self.assertEqual(client_id_field.max_length, 2048)
        client_id_field.clean(client_id_url, None)
