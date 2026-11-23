from django.db import migrations, models


def reset_marketing_consent(apps, schema_editor):
    # The old default was on, so no stored value is a real opt-in.
    UserSettings = apps.get_model("users", "UserSettings")
    UserSettings.objects.filter(notify_marketing=True).update(notify_marketing=False)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0016_profile_photos"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usersettings",
            name="notify_marketing",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(reset_marketing_consent, migrations.RunPython.noop),
    ]
