from django.contrib import admin

from .models import Quiz, QuizProgress, SharedQuiz


class QuizAdmin(admin.ModelAdmin):
    list_display = ["title", "maintainer", "visibility", "is_anonymous", "version"]
    list_filter = ["visibility", "is_anonymous"]
    search_fields = ["title", "maintainer__first_name", "maintainer__last_name"]
    readonly_fields = ["version"]


class QuizProgressAdmin(admin.ModelAdmin):
    list_display = ["quiz", "user", "current_question"]
    search_fields = ["quiz__title", "user__first_name", "user__last_name"]


class SharedQuizAdmin(admin.ModelAdmin):
    list_display = ["quiz", "user", "study_group"]
    search_fields = [
        "quiz__title",
        "user__first_name",
        "user__last_name",
        "study_group__name",
    ]


admin.site.register(Quiz, QuizAdmin)
admin.site.register(QuizProgress, QuizProgressAdmin)
admin.site.register(SharedQuiz, SharedQuizAdmin)
