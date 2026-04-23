# Originally: rename user->owner, add created_at, updated_at
# These changes were squashed into 0004_folder_quiz_folder on this branch.
# This migration is kept as a no-op for backwards compatibility with
# environments that already applied it.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('quizzes', '0004_folder_quiz_folder'),
    ]

    operations = []
