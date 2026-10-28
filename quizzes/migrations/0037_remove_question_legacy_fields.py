from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("quizzes", "0036_question_type_data")]
    operations = [
        migrations.RemoveField(
            model_name="question",
            name="is_flashcard",
        ),
        migrations.RemoveField(
            model_name="question",
            name="multiple",
        ),
        migrations.RemoveField(
            model_name="question",
            name="question_type",
        ),
        migrations.RemoveField(
            model_name="question",
            name="tf_answer",
        ),
    ]
