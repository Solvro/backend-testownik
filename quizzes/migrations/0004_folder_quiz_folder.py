import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("quizzes", "0003_sharedquiz_allow_edit"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Folder",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=128)),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True, default=django.utils.timezone.now
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="folders",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="quizzes.folder",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="quiz",
            name="folder",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="quizzes",
                to="quizzes.folder",
            ),
        ),
    ]
