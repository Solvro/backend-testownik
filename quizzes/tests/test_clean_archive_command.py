from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from quizzes.models import Folder, Quiz, Type
from users.models import User


class CleanArchiveCommandTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="commanduser@example.com", password="password123", first_name="Command", last_name="User"
        )
        self.archive_folder = Folder.objects.get(owner=self.user, folder_type=Type.ARCHIVE)
        self.root_folder = self.user.root_folder

        self.quiz_old_archive = Quiz.objects.create(title="Old Archive", creator=self.user, folder=self.archive_folder)
        self.quiz_new_archive = Quiz.objects.create(title="New Archive", creator=self.user, folder=self.archive_folder)
        self.quiz_old_normal = Quiz.objects.create(title="Old Normal", creator=self.user, folder=self.root_folder)

        thirty_one_days_ago = timezone.now() - timedelta(days=31)

        Quiz.objects.filter(id=self.quiz_old_archive.id).update(updated_at=thirty_one_days_ago)
        Quiz.objects.filter(id=self.quiz_old_normal.id).update(updated_at=thirty_one_days_ago)

    def test_clean_archive_quizzes_command(self):
        """Test that the clean_archive_quizzes command only deletes quizzes in the archive folder older than 30 days."""
        out = StringIO()

        call_command("clean_archive_quizzes", stdout=out)

        self.assertFalse(
            Quiz.objects.filter(id=self.quiz_old_archive.id).exists(), "Old quiz in archive should be deleted."
        )
        self.assertTrue(
            Quiz.objects.filter(id=self.quiz_new_archive.id).exists(), "New quiz in archive should be kept."
        )
        self.assertTrue(
            Quiz.objects.filter(id=self.quiz_old_normal.id).exists(), "Old quiz in normal folder should be kept."
        )

    def test_clean_archive_quizzes_empty(self):
        """Test command when there is nothing to delete."""
        Quiz.objects.all().delete()
        out = StringIO()

        call_command("clean_archive_quizzes", stdout=out)
        self.assertEqual(Quiz.objects.count(), 0)
