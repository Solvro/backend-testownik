from django.db.models.signals import post_save
from django.dispatch import receiver

from quizzes.models import Folder, Type
from users.models import User


@receiver(post_save, sender=User)
def create_archive_folder(sender, instance, created, **kwargs):
    """
    Creates archive folder for each new user
    """
    if created:
        Folder.objects.create(name="Archiwum", owner=instance, folder_type=Type.ARCHIVE)
