# Originally: add parent field to Folder
# This change was squashed into 0004_folder_quiz_folder on this branch.
# This migration is kept as a no-op for backwards compatibility with
# environments that already applied it.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('quizzes', '0005_rename_user_folder_owner_folder_created_at_and_more'),
    ]

    operations = []
