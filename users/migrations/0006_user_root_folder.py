from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_add_user_ban_fields"),
        ("quizzes", "0020_rename_maintainer_to_creator"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="root_folder",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="root_owner",
                to="quizzes.folder",
            ),
        ),
    ]
