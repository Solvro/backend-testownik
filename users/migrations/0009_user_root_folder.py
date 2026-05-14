import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0008_user_account_level"),
        ("quizzes", "0016_quizsession_updated_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="root_folder",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="root_owner",
                to="quizzes.folder",
            ),
        ),
    ]
