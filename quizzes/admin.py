import re

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

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
    autocomplete_fields = ["image_upload"]


class QuestionAdmin(admin.ModelAdmin):
    list_display = ["quiz", "order", "text", "multiple"]
    list_filter = ["multiple"]
    search_fields = ["text", "quiz__title"]
    inlines = [AnswerInline]
    autocomplete_fields = ["quiz"]

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)

        referer = request.META.get("HTTP_REFERER", "")
        # Check if we are editing a QuizSession
        match = re.search(r"/quizzes/quizsession/([^/]+)/change/", referer)

        if match:
            session_id = match.group(1)
            try:
                session = QuizSession.objects.get(id=session_id)
                queryset = queryset.filter(quiz=session.quiz)
            except (QuizSession.DoesNotExist, ValueError):
                # Session not found or invalid ID - fall back to unfiltered queryset
                pass

        return queryset, use_distinct


class AnswerRecordInline(admin.TabularInline):
    model = AnswerRecord
    extra = 0
    readonly_fields = ["answered_at", "was_correct", "selected_answers"]
    autocomplete_fields = ["question"]
    can_delete = False

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
        "updated_at",
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
    list_display = [
        "title",
        "maintainer",
        "visibility",
        "is_anonymous",
        "version",
        "view_questions_link",
        "view_sessions_link",
    ]
    list_filter = ["visibility", "is_anonymous"]
    search_fields = [
        "title",
        "description",
        "maintainer__first_name",
        "maintainer__last_name",
        "maintainer__email",
        "maintainer__student_number",
    ]
    readonly_fields = ["version", "created_at", "updated_at", "view_questions_link", "view_sessions_link"]
    autocomplete_fields = ["maintainer", "folder"]
    date_hierarchy = "created_at"

    def view_questions_link(self, obj):
        count = obj.questions.count()
        url = reverse("admin:quizzes_question_changelist") + f"?quiz__id__exact={obj.id}"
        return format_html('<a href="{}">View {} Questions</a>', url, count)

    view_questions_link.short_description = "Questions"

    def view_sessions_link(self, obj):
        count = obj.sessions.count()
        url = reverse("admin:quizzes_quizsession_changelist") + f"?quiz__id__exact={obj.id}"
        return format_html('<a href="{}">View {} Sessions</a>', url, count)

    view_sessions_link.short_description = "Sessions"


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
    autocomplete_fields = ["quiz", "user", "study_group"]


admin.site.register(Quiz, QuizAdmin)
admin.site.register(Question, QuestionAdmin)
admin.site.register(QuizSession, QuizSessionAdmin)
admin.site.register(QuizProgress, QuizProgressAdmin)
admin.site.register(SharedQuiz, SharedQuizAdmin)
admin.site.register(Folder, FolderAdmin)
