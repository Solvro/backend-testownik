from datetime import timedelta
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from quizzes.models import Folder, Quiz, QuizSession
from users.models import User


class CleanupGuestUsersCommandTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.old = self.now - timedelta(days=31)

    def make_old_guest(self):
        guest = User.objects.create_guest_user()
        User.objects.filter(pk=guest.pk).update(updated_at=self.old)
        guest.refresh_from_db()
        return guest

    def test_deletes_inactive_guest_and_associated_data(self):
        guest = self.make_old_guest()
        root_id = guest.root_folder_id
        folder = Folder.objects.create(name="Guest folder", owner=guest, parent=guest.root_folder)
        quiz = Quiz.objects.create(title="Guest quiz", creator=guest, folder=folder)
        session = QuizSession.objects.create(quiz=quiz, user=guest)
        Quiz.objects.filter(pk=quiz.pk).update(updated_at=self.old)
        QuizSession.objects.filter(pk=session.pk).update(updated_at=self.old)

        call_command("cleanup_guest_users")

        self.assertFalse(User.objects.filter(pk=guest.pk).exists())
        self.assertFalse(Folder.objects.filter(pk__in=[root_id, folder.pk]).exists())
        self.assertFalse(Quiz.objects.filter(pk=quiz.pk).exists())
        self.assertFalse(QuizSession.objects.filter(pk=session.pk).exists())

    def test_keeps_recent_guest(self):
        guest = User.objects.create_guest_user()

        call_command("cleanup_guest_users")

        self.assertTrue(User.objects.filter(pk=guest.pk).exists())

    def test_recent_quiz_edit_keeps_guest_with_old_user_timestamp(self):
        guest = self.make_old_guest()
        Quiz.objects.create(title="Recently edited", creator=guest, folder=guest.root_folder)

        call_command("cleanup_guest_users")

        self.assertTrue(User.objects.filter(pk=guest.pk).exists())

    def test_recent_session_keeps_guest_with_old_user_and_quiz_timestamps(self):
        guest = self.make_old_guest()
        quiz = Quiz.objects.create(title="Old quiz", creator=guest, folder=guest.root_folder)
        Quiz.objects.filter(pk=quiz.pk).update(updated_at=self.old)
        QuizSession.objects.create(quiz=quiz, user=guest)

        call_command("cleanup_guest_users")

        self.assertTrue(User.objects.filter(pk=guest.pk).exists())

    def test_dry_run_only_previews_deletion(self):
        guest = self.make_old_guest()
        out = StringIO()

        call_command("cleanup_guest_users", dry_run=True, stdout=out)

        self.assertTrue(User.objects.filter(pk=guest.pk).exists())
        self.assertIn("DRY RUN", out.getvalue())
        self.assertIn("Would delete 1 guest users", out.getvalue())

    def test_does_not_delete_inactive_regular_user(self):
        user = User.objects.create_user(
            email="regular@example.com",
            password="password",
            first_name="Regular",
            last_name="User",
        )
        User.objects.filter(pk=user.pk).update(updated_at=self.old)

        call_command("cleanup_guest_users")

        self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_custom_days_threshold(self):
        guest = User.objects.create_guest_user()
        five_days_ago = self.now - timedelta(days=5)
        User.objects.filter(pk=guest.pk).update(updated_at=five_days_ago)

        call_command("cleanup_guest_users", days=3)

        self.assertFalse(User.objects.filter(pk=guest.pk).exists())

    def test_negative_days_are_rejected(self):
        with self.assertRaises(CommandError):
            call_command("cleanup_guest_users", days=-1)

    def test_verbose_output_contains_activity_and_counts(self):
        guest = self.make_old_guest()
        out = StringIO()

        call_command("cleanup_guest_users", dry_run=True, verbose=True, stdout=out)

        output = out.getvalue()
        self.assertIn(str(guest.id), output)
        self.assertIn("last activity:", output)
        self.assertIn("quizzes: 0 | sessions: 0", output)
