from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from quizzes.models import Folder, FolderType, Quiz
from users.models import User


class CleanArchiveCommandTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="commanduser@example.com", password="password123", first_name="Command", last_name="User"
        )
        self.archive_folder = Folder.objects.get(owner=self.user, folder_type=FolderType.ARCHIVE)
        self.root_folder = self.user.root_folder

        self.quiz_old_archive = Quiz.objects.create(title="Old Archive", creator=self.user, folder=self.archive_folder)
        self.quiz_new_archive = Quiz.objects.create(title="New Archive", creator=self.user, folder=self.archive_folder)
        self.quiz_old_normal = Quiz.objects.create(title="Old Normal", creator=self.user, folder=self.root_folder)

        past_ttl = timezone.now() - timedelta(days=settings.ARCHIVE_TTL_DAYS + 1)

        Quiz.objects.filter(id=self.quiz_old_archive.id).update(archived_at=past_ttl)
        Quiz.objects.filter(id=self.quiz_old_normal.id).update(updated_at=past_ttl)

    def test_clean_archive_quizzes_command(self):
        """Only quizzes in the archive folder older than ARCHIVE_TTL_DAYS are deleted."""
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
