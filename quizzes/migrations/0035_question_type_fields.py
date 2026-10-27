from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("quizzes", "0034_quiz_version")]
    operations = [
        migrations.AddField(
            model_name="question",
            name="open_matching",
            field=models.CharField(
                choices=[("exact", "Dokładne"), ("similar", "Podobne")],
                default="exact",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="question",
            name="type",
            field=models.CharField(
                choices=[
                    ("single_choice", "Jednokrotny wybór"),
                    ("multiple_choice", "Wielokrotny wybór"),
                    ("true_false", "Prawda/Fałsz"),
                    ("open", "Otwarte"),
                ],
                default="single_choice",
                max_length=20,
            ),
        ),
    ]
