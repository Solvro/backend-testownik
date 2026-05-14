import uuid

from django.db import migrations, transaction


def backfill_archive_folders(apps, schema_editor):
    User = apps.get_model("users", "User")
    Folder = apps.get_model("quizzes", "Folder")

    users_needing_archive = User.objects.filter(
        root_folder__isnull=False,
    ).exclude(
        folders__folder_type="archive",
    )

    with transaction.atomic():
        for user in users_needing_archive.iterator():
            Folder.objects.get_or_create(
                owner=user,
                folder_type="archive",
                defaults={
                    "id": uuid.uuid4(),
                    "name": "Archiwum",
                    "parent": user.root_folder,
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ("quizzes", "0027_folder_folder_type_folder_unique_archive_per_user"),
    ]

    operations = [
        migrations.RunPython(backfill_archive_folders, migrations.RunPython.noop),
    ]
