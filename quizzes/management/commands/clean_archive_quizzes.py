from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from quizzes.models import FolderType, Quiz


class Command(BaseCommand):
    help = "Deletes quizzes located in the Archive folder for more than ARCHIVE_TTL_DAYS days"

    def handle(self, *args, **kwargs):
        ttl_days = settings.ARCHIVE_TTL_DAYS
        cutoff_date = timezone.now() - timedelta(days=ttl_days)

        quizzes_to_delete = Quiz.objects.filter(folder__folder_type=FolderType.ARCHIVE, archived_at__lt=cutoff_date)

        quizzes_to_delete.delete()
