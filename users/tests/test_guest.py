"""
Tests for guest account creation and guest-to-user migration.
"""

import uuid
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Folder, Quiz, QuizSession
from users.models import AccountType, EmailLoginToken, User
from users.services import migrate_guest_to_user

# ---------------------------------------------------------------------------
# Unit tests for migrate_guest_to_user service
# ---------------------------------------------------------------------------


class MigrateGuestToUserTestCase(TestCase):
    """Tests for the migrate_guest_to_user service function."""

    def setUp(self):
        self.target_user = User.objects.create_user(
            email="target@example.com",
            first_name="Target",
            last_name="User",
            student_number="111111",
        )
        self.guest = User.objects.create_guest_user()

    # --- success cases ---

    def test_migrate_quizzes(self):
        """Quizzes owned by the guest are transferred to the target user."""
        quiz = Quiz.objects.create(title="Guest Quiz", maintainer=self.guest)

        result = migrate_guest_to_user(str(self.guest.id), self.target_user)

        self.assertTrue(result)
        quiz.refresh_from_db()
        self.assertEqual(quiz.maintainer, self.target_user)

    def test_migrate_sessions_no_conflict(self):
        """Sessions are transferred when the target has no session for that quiz."""
        quiz = Quiz.objects.create(title="Quiz", maintainer=self.target_user)
        QuizSession.objects.create(quiz=quiz, user=self.guest, is_active=True)

        result = migrate_guest_to_user(str(self.guest.id), self.target_user)

        self.assertTrue(result)
        self.assertEqual(QuizSession.objects.filter(user=self.target_user, quiz=quiz, is_active=True).count(), 1)

    def test_migrate_sessions_with_conflict_archives_older(self):
        """When both guest and target have an active session for the same quiz,
        the older one is archived."""
        quiz = Quiz.objects.create(title="Quiz", maintainer=self.target_user)
        guest_session = QuizSession.objects.create(quiz=quiz, user=self.guest, is_active=True)
        target_session = QuizSession.objects.create(quiz=quiz, user=self.target_user, is_active=True)

        # Make guest session newer so that target session gets archived
        QuizSession.objects.filter(pk=guest_session.pk).update(
            updated_at=target_session.updated_at + timedelta(seconds=10)
        )

        result = migrate_guest_to_user(str(self.guest.id), self.target_user)

        self.assertTrue(result)
        target_session.refresh_from_db()
        self.assertFalse(target_session.is_active)
        # Both sessions should now belong to target
        self.assertEqual(QuizSession.objects.filter(user=self.target_user, quiz=quiz).count(), 2)

    def test_migrate_folders(self):
        """Folders owned by the guest are transferred to the target user."""
        folder = Folder.objects.create(name="Guest Folder", owner=self.guest)

        result = migrate_guest_to_user(str(self.guest.id), self.target_user)

        self.assertTrue(result)
        folder.refresh_from_db()
        self.assertEqual(folder.owner, self.target_user)

    def test_guest_is_deleted_after_migration(self):
        """The guest account is deleted after successful migration."""
        guest_id = str(self.guest.id)

        result = migrate_guest_to_user(guest_id, self.target_user)

        self.assertTrue(result)
        self.assertFalse(User.objects.filter(id=guest_id).exists())

    # --- failure cases ---

    def test_empty_guest_id_returns_false(self):
        """Empty guest_id returns False immediately."""
        self.assertFalse(migrate_guest_to_user("", self.target_user))

    def test_nonexistent_guest_returns_false(self):
        """Non-existent guest UUID returns False."""
        self.assertFalse(migrate_guest_to_user(str(uuid.uuid4()), self.target_user))

    def test_invalid_uuid_returns_false(self):
        """An invalid (non-UUID) guest_id returns False instead of raising."""
        self.assertFalse(migrate_guest_to_user("not-a-uuid", self.target_user))

    def test_non_guest_account_returns_false(self):
        """Attempting to migrate a non-guest account returns False."""
        regular_user = User.objects.create_user(
            email="regular@example.com",
            first_name="Regular",
            last_name="User",
            student_number="222222",
        )
        self.assertFalse(migrate_guest_to_user(str(regular_user.id), self.target_user))
        # Regular user should NOT be deleted
        self.assertTrue(User.objects.filter(id=regular_user.id).exists())

    def test_same_user_returns_false(self):
        """Migrating a guest to itself returns False."""
        self.assertFalse(migrate_guest_to_user(str(self.guest.id), self.guest))


# ---------------------------------------------------------------------------
# API tests for GuestCreateView
# ---------------------------------------------------------------------------

INTERNAL_API_KEY = "test-internal-key-12345"


@override_settings(INTERNAL_API_KEY=INTERNAL_API_KEY)
class GuestCreateViewTestCase(APITestCase):
    """Tests for the guest account creation endpoint."""

    def setUp(self):
        self.url = reverse("guest_create")

    def test_create_guest_returns_201_and_sets_cookies(self):
        """Successful guest creation returns 201 and sets JWT cookies."""
        response = self.client.post(self.url, HTTP_API_KEY=INTERNAL_API_KEY)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)
        self.assertEqual(response.data["message"], "Guest account created")

    def test_guest_user_is_created_in_db(self):
        """A guest user record is persisted with account_type=GUEST."""
        self.client.post(self.url, HTTP_API_KEY=INTERNAL_API_KEY)

        guest = User.objects.filter(account_type=AccountType.GUEST).first()
        self.assertIsNotNone(guest)
        self.assertIsNone(guest.email)
        self.assertFalse(guest.has_usable_password())

    def test_missing_api_key_is_rejected(self):
        """Request without Api-Key header is rejected."""
        response = self.client.post(self.url)

        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_wrong_api_key_is_rejected(self):
        """Request with incorrect Api-Key header is rejected."""
        response = self.client.post(self.url, HTTP_API_KEY="wrong-key")

        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_jwt_contains_guest_account_type(self):
        """The JWT token embeds account_type='guest'."""
        response = self.client.post(self.url, HTTP_API_KEY=INTERNAL_API_KEY)

        from rest_framework_simplejwt.tokens import AccessToken

        access = AccessToken(response.cookies["access_token"].value, verify=False)
        self.assertEqual(access["account_type"], AccountType.GUEST)


# ---------------------------------------------------------------------------
# Integration tests for guest migration during login flows
# ---------------------------------------------------------------------------


class GuestMigrationOnOTPLoginTestCase(APITestCase):
    """Tests that guest migration is triggered during OTP login."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com",
            first_name="Real",
            last_name="User",
            student_number="333333",
        )
        self.guest = User.objects.create_guest_user()
        self.quiz = Quiz.objects.create(title="Guest Quiz", maintainer=self.guest)

    def test_otp_login_migrates_guest_data(self):
        """OTP login with valid guest_id migrates quizzes to the logged-in user when authenticated as guest."""
        token = EmailLoginToken.create_for_user(self.user)

        self.client.force_authenticate(user=self.guest)

        response = self.client.post(
            reverse("login_otp"),
            {"email": "user@example.com", "otp": token.otp_code, "guest_id": str(self.guest.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.maintainer, self.user)
        self.assertFalse(User.objects.filter(id=self.guest.id).exists())

    def test_otp_login_without_guest_id_skips_migration(self):
        """OTP login without guest_id does not trigger migration."""
        token = EmailLoginToken.create_for_user(self.user)

        response = self.client.post(
            reverse("login_otp"),
            {"email": "user@example.com", "otp": token.otp_code},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.maintainer, self.guest)  # unchanged


class GuestMigrationOnLinkLoginTestCase(APITestCase):
    """Tests that guest migration is triggered during magic-link login."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com",
            first_name="Real",
            last_name="User",
            student_number="333333",
        )
        self.guest = User.objects.create_guest_user()
        self.quiz = Quiz.objects.create(title="Guest Quiz", maintainer=self.guest)

    def test_link_login_migrates_guest_data(self):
        """Link login with valid guest_id migrates quizzes to the logged-in user when authenticated as guest."""
        token = EmailLoginToken.create_for_user(self.user)

        self.client.force_authenticate(user=self.guest)

        response = self.client.post(
            reverse("login_link"),
            {"token": str(token.token), "guest_id": str(self.guest.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.maintainer, self.user)
        self.assertFalse(User.objects.filter(id=self.guest.id).exists())

    def test_link_login_without_guest_id_skips_migration(self):
        """Link login without guest_id does not trigger migration."""
        token = EmailLoginToken.create_for_user(self.user)

        response = self.client.post(
            reverse("login_link"),
            {"token": str(token.token)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.maintainer, self.guest)  # unchanged
