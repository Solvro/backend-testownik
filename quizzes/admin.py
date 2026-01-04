from django.contrib import admin

from .models import Quiz, QuizProgress, SharedQuiz


class QuizAdmin(admin.ModelAdmin):
    list_display = ["title", "maintainer", "visibility", "is_anonymous", "version", "created_at", "updated_at"]
    list_filter = ["visibility", "is_anonymous", "allow_anonymous", "created_at", "updated_at"]
    search_fields = [
        "title",
        "description",
        "maintainer__first_name",
        "maintainer__last_name",
        "maintainer__email",
        "maintainer__student_number",
    ]
    readonly_fields = ["version", "created_at", "updated_at"]
    date_hierarchy = "created_at"


class QuizProgressAdmin(admin.ModelAdmin):
    list_display = ["quiz", "user", "current_question", "correct_answers_count", "wrong_answers_count", "last_activity"]
    list_filter = ["last_activity"]
    search_fields = ["quiz__title", "user__first_name", "user__last_name", "user__email", "user__student_number"]
    date_hierarchy = "last_activity"


class SharedQuizAdmin(admin.ModelAdmin):
    list_display = ["quiz", "user", "study_group", "allow_edit"]
    list_filter = ["allow_edit"]
    search_fields = [
        "quiz__title",
        "user__first_name",
        "user__last_name",
        "user__email",
        "user__student_number",
        "study_group__name",
    ]


admin.site.register(Quiz, QuizAdmin)
admin.site.register(QuizProgress, QuizProgressAdmin)
admin.site.register(SharedQuiz, SharedQuizAdmin)
