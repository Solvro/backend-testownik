from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("quizzes", "0034_alter_folder_for_shared_drive"),
    ]

    operations = [
        migrations.AddField(
            model_name="folder",
            name="shared_drive",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="drive_folders",
                to="quizzes.folder",
            ),
        ),
    ]
