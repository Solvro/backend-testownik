# quizzes/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from users.models import User
from quizzes.models import Folder

@receiver(post_save, sender=User)
def create_archive_folder(sender, instance, created, **kwargs):
    """
    Creates archive folder for each new user
    """
    if created:
        Folder.objects.create(
            name="Archive",
            owner=instance,
            folder_type=Folder.Type.ARCHIVE
        )