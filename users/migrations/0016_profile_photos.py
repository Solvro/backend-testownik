import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("uploads", "0001_initial"),
        ("users", "0015_merge_email_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="custom_photo_image",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="user_custom_photos",
                to="uploads.uploadedimage",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="photo_image",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="user_photos",
                to="uploads.uploadedimage",
            ),
        ),
        # photo_url stays as the provider photo source; overriden_photo_url for the backfill.
    ]
