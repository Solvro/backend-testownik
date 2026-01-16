from django.contrib import admin

from .models import (
    Answer,
    AnswerRecord,
    Folder,
    Question,
    Quiz,
    QuizProgress,
    QuizSession,
    SharedQuiz,
)


class FolderAdmin(admin.ModelAdmin):
    search_fields = ["name", "owner__first_name", "owner__last_name", "owner__email"]
    autocomplete_fields = ["owner", "parent"]


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 1


class QuestionInline(admin.StackedInline):
    model = Question
    extra = 0
    show_change_link = True


class QuestionAdmin(admin.ModelAdmin):
    list_display = ["quiz", "order", "text", "multiple"]
    list_filter = ["quiz", "multiple"]
    search_fields = ["text", "quiz__title"]
    inlines = [AnswerInline]
    autocomplete_fields = ["quiz"]


class AnswerRecordInline(admin.TabularInline):
    model = AnswerRecord
    extra = 0
    readonly_fields = ["answered_at", "was_correct", "selected_answers"]
    autocomplete_fields = ["question"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class QuizSessionInline(admin.TabularInline):
    model = QuizSession
    extra = 0
    readonly_fields = ["started_at", "ended_at", "score_display", "is_active"]
    fields = ["user", "started_at", "ended_at", "is_active", "score_display"]
    can_delete = False
    show_change_link = True

    def score_display(self, obj):
        return f"{obj.correct_count} / {obj.correct_count + obj.wrong_count}"

    score_display.short_description = "Score"

    def has_add_permission(self, request, obj=None):
        return False


class QuizSessionAdmin(admin.ModelAdmin):
    list_display = [
        "quiz",
        "user",
        "is_active",
        "started_at",
        "correct_count_display",
        "wrong_count_display",
    ]
    list_filter = ["is_active", "started_at"]
    search_fields = ["quiz__title", "user__first_name", "user__last_name", "user__email"]
    autocomplete_fields = ["quiz", "user", "current_question"]
    inlines = [AnswerRecordInline]
    readonly_fields = ["correct_count_display", "wrong_count_display"]

    def correct_count_display(self, obj):
        return obj.correct_count

    correct_count_display.short_description = "Correct"

    def wrong_count_display(self, obj):
        return obj.wrong_count

    wrong_count_display.short_description = "Wrong"


class QuizAdmin(admin.ModelAdmin):
    list_display = ["title", "maintainer", "visibility", "is_anonymous", "version"]
    list_filter = ["visibility", "is_anonymous"]
    search_fields = ["title", "maintainer__first_name", "maintainer__last_name", "maintainer__email"]
    readonly_fields = ["version"]
    autocomplete_fields = ["maintainer", "folder"]
    inlines = [QuestionInline, QuizSessionInline]


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
    autocomplete_fields = ["quiz", "user", "study_group"]


admin.site.register(Quiz, QuizAdmin)
admin.site.register(Question, QuestionAdmin)
admin.site.register(QuizSession, QuizSessionAdmin)
admin.site.register(QuizProgress, QuizProgressAdmin)
admin.site.register(SharedQuiz, SharedQuizAdmin)
admin.site.register(Folder, FolderAdmin)
