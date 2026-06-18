import uuid

from django.db import migrations, models, transaction


def backfill_trash_folders(apps, schema_editor):
    User = apps.get_model("users", "User")
    Folder = apps.get_model("quizzes", "Folder")

    users_needing_trash = User.objects.filter(
        root_folder__isnull=False,
    ).exclude(
        folders__folder_type="trash",
    )

    with transaction.atomic():
        for user in users_needing_trash.iterator():
            Folder.objects.get_or_create(
                owner=user,
                folder_type="trash",
                defaults={
                    "id": uuid.uuid4(),
                    "name": "Kosz",
                    "parent": user.root_folder,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("quizzes", "0031_quiz_is_ai_generated"),
    ]

    operations = [
        migrations.AlterField(
            model_name="folder",
            name="folder_type",
            field=models.CharField(
                choices=[
                    ("archive", "Archive"),
                    ("regular", "Regular"),
                    ("trash", "Trash"),
                ],
                default="regular",
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="folder",
            constraint=models.UniqueConstraint(
                condition=models.Q(("folder_type", "trash")),
                fields=("owner", "folder_type"),
                name="unique_trash_per_user",
            ),
        ),
        migrations.AddField(
            model_name="quiz",
            name="deleted_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(backfill_trash_folders, migrations.RunPython.noop),
    ]
