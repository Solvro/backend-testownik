from datetime import timedelta

from django.contrib.auth.models import Permission
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from users.models import AccountLevel, AccountLevelGrant, AccountLevelGrantSource, User


class AccountLevelGrantModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(email="grant@example.com", account_level=AccountLevel.BASIC)

    def _grant(self, **kwargs):
        defaults = {"user": self.user, "level": AccountLevel.SILVER, "source": AccountLevelGrantSource.ADMIN}
        defaults.update(kwargs)
        return AccountLevelGrant.objects.create(**defaults)

    def test_grant_without_expiry_is_allowed_and_does_not_change_permanent_level(self):
        grant = self._grant(level=AccountLevel.GOLD, expires_at=None)

        self.assertIsNone(grant.expires_at)
        self.assertIsNotNone(grant.id)
        self.user.refresh_from_db()
        self.assertEqual(self.user.account_level, AccountLevel.BASIC)

    def test_grant_with_expiry_in_the_future_is_allowed(self):
        grant = self._grant(expires_at=timezone.now() + timedelta(days=30))

        self.assertGreater(grant.expires_at, grant.starts_at)

    def test_basic_level_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._grant(level=AccountLevel.BASIC)

    def test_expiry_not_after_start_is_rejected_by_database(self):
        starts_at = timezone.now()
        for expires_at in (starts_at, starts_at - timedelta(seconds=1)):
            with self.subTest(expires_at=expires_at), self.assertRaises(IntegrityError), transaction.atomic():
                self._grant(starts_at=starts_at, expires_at=expires_at)

    def test_source_ref_is_unique_per_source_but_many_grants_may_have_none(self):
        self._grant(source=AccountLevelGrantSource.REWARD, source_ref="ref-1")
        self._grant()
        self._grant()

        self._grant(source=AccountLevelGrantSource.GIVEAWAY, source_ref="ref-1")

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._grant(source=AccountLevelGrantSource.REWARD, source_ref="ref-1")

        self.assertEqual(AccountLevelGrant.objects.filter(user=self.user).count(), 4)

    def test_deleting_creator_keeps_the_grant(self):
        admin = User.objects.create(email="admin@example.com")
        grant = self._grant(created_by=admin)

        admin.delete()

        grant.refresh_from_db()
        self.assertIsNone(grant.created_by)

    def test_deleting_user_deletes_their_grants(self):
        self._grant()

        self.user.delete()

        self.assertFalse(AccountLevelGrant.objects.exists())

    def test_manage_account_levels_permission_exists_and_can_be_assigned(self):
        permission = Permission.objects.get(content_type__app_label="users", codename="manage_account_levels")
        self.user.user_permissions.add(permission)

        user = User.objects.get(pk=self.user.pk)

        self.assertTrue(user.has_perm("users.manage_account_levels"))
        self.assertFalse(User.objects.create(email="other@example.com").has_perm("users.manage_account_levels"))


class AccountLevelGrantMigrationTests(TransactionTestCase):
    def test_migration_keeps_existing_permanent_levels(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [("users", "0016_profile_photos")]
        try:
            executor.migrate(previous)
            old_user_model = executor.loader.project_state(previous).apps.get_model("users", "User")
            levels = {
                "basic": old_user_model.objects.create(email="basic@example.com", account_level="basic"),
                "silver": old_user_model.objects.create(email="silver@example.com", account_level="silver"),
                "gold": old_user_model.objects.create(email="gold@example.com", account_level="gold"),
            }

            executor = MigrationExecutor(connection)
            executor.migrate(latest)

            new_user_model = executor.loader.project_state(latest).apps.get_model("users", "User")
            grant_model = executor.loader.project_state(latest).apps.get_model("users", "AccountLevelGrant")
            for level, user in levels.items():
                self.assertEqual(new_user_model.objects.get(pk=user.pk).account_level, level)
            self.assertEqual(grant_model.objects.count(), 0)
        finally:
            MigrationExecutor(connection).migrate(latest)
