from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0012_usersettings_default_ai_model"),
    ]

    operations = [
        migrations.CreateModel(
            name="CourseClassType",
            fields=[
                ("id", models.CharField(max_length=32, primary_key=True, serialize=False)),
                ("name_pl", models.CharField(blank=True, max_length=255)),
                ("name_en", models.CharField(blank=True, max_length=255)),
                ("synced_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["id"],
            },
        ),
    ]
