from django.db.models.signals import post_save


def create_root_folder(sender, instance, created, **kwargs):
    if created and not instance.root_folder_id:
        from .models import Folder

        folder = Folder.objects.create(name="Moje quizy", owner=instance)
        sender.objects.filter(pk=instance.pk).update(root_folder=folder)
        instance.root_folder = folder
        instance.root_folder_id = folder.id


def register_signals():
    from users.models import User

    post_save.connect(create_root_folder, sender=User)
