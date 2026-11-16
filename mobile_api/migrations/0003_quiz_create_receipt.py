import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mobile_api", "0002_loginattempt_guest"),
        ("quizzes", "0034_quiz_shortcut"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="QuizCreateReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_id", models.UUIDField()),
                ("payload_hash", models.CharField(max_length=64)),
                ("outcome", models.CharField(choices=[("created", "Created"), ("rejected", "Rejected")], max_length=10)),
                ("original_quiz_id", models.UUIDField(null=True)),
                ("created_version", models.PositiveIntegerField(null=True)),
                ("id_map", models.JSONField(default=dict)),
                ("validation_errors", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("quiz", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="quizzes.quiz")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("user", "request_id"), name="mobile_quiz_create_once")],
            },
        ),
    ]
