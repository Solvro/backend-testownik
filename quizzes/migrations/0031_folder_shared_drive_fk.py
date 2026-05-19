from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("quizzes", "0029_alter_folder_folder_type_alter_folder_owner_and_more"),
        ("quizzes", "0030_add_ai_fields"),
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
