import uuid

from django.db import migrations


def create_root_folders(apps, schema_editor):
    User = apps.get_model("users", "User")
    Folder = apps.get_model("quizzes", "Folder")
    Quiz = apps.get_model("quizzes", "Quiz")

    # Get all users who have quizzes or need a root folder
    users = User.objects.all()

    for user in users:
        # Create root folder for each user
        folder = Folder.objects.create(
            id=uuid.uuid4(),
            name="Moje quizy",
            owner=user,
            parent=None,
        )
        # Set as root folder
        User.objects.filter(pk=user.pk).update(root_folder=folder)

        # Move quizzes without a folder to the root folder
        Quiz.objects.filter(creator=user, folder__isnull=True).update(folder=folder)




class Migration(migrations.Migration):

    dependencies = [
        ("quizzes", "0020_rename_maintainer_to_creator"),
        ("users", "0006_user_root_folder"),
    ]

    operations = [
        migrations.RunPython(create_root_folders),
    ]
