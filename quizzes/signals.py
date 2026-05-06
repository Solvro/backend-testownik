from django.db import transaction
from django.db.models.signals import post_save


def initialize_user_folders(sender, instance, created, **kwargs):
    if created and not instance.root_folder_id:
        from .models import Folder, FolderType

        with transaction.atomic():
            folder = Folder.objects.create(name=Folder.DEFAULT_ROOT_NAME, owner=instance)
            sender.objects.filter(pk=instance.pk).update(root_folder=folder)
            instance.root_folder = folder
            instance.root_folder_id = folder.id

            Folder.objects.create(
                name=Folder.DEFAULT_ARCHIVE_NAME, owner=instance, parent=folder, folder_type=FolderType.ARCHIVE
            )


def register_signals():
    from users.models import User

    post_save.connect(initialize_user_folders, sender=User, dispatch_uid="quizzes.initialize_user_folders")
