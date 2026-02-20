import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("quizzes", "0021_create_root_folders"),
    ]

    operations = [
        migrations.AlterField(
            model_name="quiz",
            name="folder",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="quizzes",
                to="quizzes.folder",
            ),
        ),
    ]
