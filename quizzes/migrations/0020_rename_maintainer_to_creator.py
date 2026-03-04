from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("quizzes", "0019_merge_0017_sharedfolder_0018_delete_quizprogress"),
    ]

    operations = [
        # Rename maintainer -> creator
        migrations.RenameField(
            model_name="quiz",
            old_name="maintainer",
            new_name="creator",
        ),
        # Update related_name on creator
        migrations.AlterField(
            model_name="quiz",
            name="creator",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="created_quizzes",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
