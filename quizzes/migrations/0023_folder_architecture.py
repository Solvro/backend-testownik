import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_root_folders(apps, schema_editor):
    User = apps.get_model("users", "User")
    Folder = apps.get_model("quizzes", "Folder")
    Quiz = apps.get_model("quizzes", "Quiz")

    for user in User.objects.all().iterator():
        if user.root_folder_id:
            folder = Folder.objects.get(pk=user.root_folder_id)
        else:
            folder = Folder.objects.create(
                id=uuid.uuid4(),
                name="Moje quizy",
                owner=user,
                parent=None,
            )
            User.objects.filter(pk=user.pk).update(root_folder=folder)
        Quiz.objects.filter(creator=user, folder__isnull=True).update(folder=folder)


class Migration(migrations.Migration):

    dependencies = [
        ("quizzes", "0022_question_is_markdown_enabled"),
        ("users", "0009_user_root_folder"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SharedFolder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("allow_edit", models.BooleanField(default=False)),
                ("folder", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="shares", to="quizzes.folder")),
                ("study_group", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="shared_folders", to="users.studygroup")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="shared_folders", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.RenameField(
            model_name="quiz",
            old_name="maintainer",
            new_name="creator",
        ),
        migrations.AlterField(
            model_name="quiz",
            name="creator",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="created_quizzes",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(create_root_folders, migrations.RunPython.noop),
    ]
