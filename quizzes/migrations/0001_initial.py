# Generated by Django 5.1.4 on 2025-01-24 19:28

import datetime
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Quiz',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, null=True)),
                ('visibility', models.PositiveIntegerField(choices=[(0, 'Prywatny'), (1, 'Dla udostępnionych'), (2, 'Niepubliczny (z linkiem)'), (3, 'Publiczny')], default=2)),
                ('allow_anonymous', models.BooleanField(default=False, help_text='Każdy, nawet niezalogowany użytkownik będzie mógł wyświetlić tę bazę wchodząc na link')),
                ('is_anonymous', models.BooleanField(default=False, help_text='Nie będzie wyświetlany autor testu, cały czas będzie można zgłosić błąd w pytaniu')),
                ('version', models.PositiveIntegerField(default=1)),
                ('questions', models.JSONField(blank=True, default=list)),
            ],
        ),
        migrations.CreateModel(
            name='QuizProgress',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('current_question', models.PositiveIntegerField(default=0)),
                ('reoccurrences', models.JSONField(blank=True, default=list)),
                ('correct_answers_count', models.PositiveIntegerField(default=0)),
                ('wrong_answers_count', models.PositiveIntegerField(default=0)),
                ('study_time', models.DurationField(default=datetime.timedelta)),
                ('last_activity', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='SharedQuiz',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ],
        ),
    ]
