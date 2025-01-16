from django.contrib import admin

from .models import Quiz, QuizProgress, SharedQuiz

admin.site.register(Quiz)
admin.site.register(SharedQuiz)
admin.site.register(QuizProgress)
