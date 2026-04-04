from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from quizzes.models import Quiz, Type


class Command(BaseCommand):
    help = "Deletes quizzes located in the Archive folder for more than 30 days"

    def handle(self, *args, **kwargs):
        thirty_days_ago = timezone.now() - timedelta(days=30)

        quizzes_to_delete = Quiz.objects.filter(folder__folder_type=Type.ARCHIVE, updated_at__lt=thirty_days_ago)

        quizzes_to_delete.delete()
