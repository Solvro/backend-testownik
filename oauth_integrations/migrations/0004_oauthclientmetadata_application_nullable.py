import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("oauth_integrations", "0003_auto_20260928_1324"),
    ]

    operations = [
        migrations.AlterField(
            model_name="oauthclientmetadata",
            name="application",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="cimd_metadata",
                to=settings.OAUTH2_PROVIDER_APPLICATION_MODEL,
                swappable=False,
            ),
        ),
    ]
