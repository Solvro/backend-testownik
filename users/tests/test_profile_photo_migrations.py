from unittest.mock import patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ProfilePhotoMigrationTests(TransactionTestCase):
    def test_upgrade_from_dev_preserves_legacy_photo_without_network(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [("users", "0015_merge_email_profile")]
        try:
            executor.migrate(previous)
            old_user = executor.loader.project_state(previous).apps.get_model("users", "User")
            user = old_user.objects.create(
                email="migration@example.com",
                first_name="Anna",
                last_name="Nowak",
                overriden_photo_url="https://api.dicebear.com/9.x/micah/svg?seed=legacy",
            )
            with patch("socket.getaddrinfo") as dns, patch("requests.get") as download:
                executor = MigrationExecutor(connection)
                executor.migrate(latest)
            dns.assert_not_called()
            download.assert_not_called()
            new_user = executor.loader.project_state(latest).apps.get_model("users", "User")
            migrated = new_user.objects.get(pk=user.pk)
            self.assertEqual(migrated.first_name, "Anna")
            self.assertEqual(migrated.overriden_photo_url, user.overriden_photo_url)
            self.assertIsNone(migrated.photo_image_id)
            self.assertIsNone(migrated.custom_photo_image_id)
            self.assertNotIn("photo_url", {field.name for field in new_user._meta.fields})
        finally:
            MigrationExecutor(connection).migrate(latest)
