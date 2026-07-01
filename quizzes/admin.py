import re

from django.conf import settings
from django.contrib import admin
from django.db.models import Count
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.decorators import action
from unfold.enums import ActionVariant

from .models import (
    Answer,
    AnswerRecord,
    Comment,
    Folder,
    Question,
    QuestionChangeSuggestion,
    Quiz,
    QuizSession,
    SharedQuiz,
)


class AnswerInline(TabularInline):
    model = Answer
    extra = 1
    autocomplete_fields = ["image_upload"]


class QuestionInline(StackedInline):
    model = Question
    extra = 0
    show_change_link = True
    autocomplete_fields = ["image_upload"]


@admin.register(Question)
class QuestionAdmin(ModelAdmin):
    list_display = ["quiz", "order", "text", "multiple", "is_ai_generated"]
    list_filter = ["multiple", "is_ai_generated"]
    search_fields = ["text", "quiz__title"]
    inlines = [AnswerInline]
    autocomplete_fields = ["quiz", "image_upload"]

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)

        referer = request.META.get("HTTP_REFERER", "")
        match = re.search(r"/quizzes/quizsession/([^/]+)/change/", referer)

        if match:
            session_id = match.group(1)
            try:
                session = QuizSession.objects.get(id=session_id)
                queryset = queryset.filter(quiz=session.quiz)
            except (QuizSession.DoesNotExist, ValueError):
                pass

        return queryset, use_distinct


class AnswerRecordInline(TabularInline):
    model = AnswerRecord
    extra = 0
    readonly_fields = ["answered_at", "was_correct", "selected_answers"]
    autocomplete_fields = ["question"]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(QuizSession)
class QuizSessionAdmin(ModelAdmin):
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


@admin.register(Quiz)
class QuizAdmin(ModelAdmin):
    actions_detail = ["open_in_app"]
    list_display = [
        "title",
        "creator",
        "visibility",
        "is_anonymous",
        "is_ai_generated",
        "version",
        "created_at",
        "view_questions_link",
        "view_sessions_link",
    ]
    list_filter = ["visibility", "is_anonymous", "is_ai_generated"]
    search_fields = [
        "title",
        "description",
        "creator__first_name",
        "creator__last_name",
        "creator__email",
        "creator__student_number",
    ]
    readonly_fields = ["version", "created_at", "updated_at", "view_questions_link", "view_sessions_link"]
    autocomplete_fields = ["creator", "folder"]
    date_hierarchy = "created_at"

    # noinspection PyCallingNonCallable
    @action(
        description="Open in App",
        icon="open_in_new",
        variant=ActionVariant.DEFAULT,
        attrs={"target": "_blank", "rel": "noopener noreferrer"},
    )
    def open_in_app(self, request, object_id):
        frontend_url = settings.FRONTEND_URL.rstrip("/")
        return redirect(f"{frontend_url}/quiz/{object_id}")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.annotate(sessions_count=Count("sessions"))

    def view_questions_link(self, obj):
        count = obj.questions.count()
        url = reverse("admin:quizzes_question_changelist") + f"?quiz__id__exact={obj.id}"
        return format_html('<a href="{}">View {} Questions</a>', url, count)

    view_questions_link.short_description = "Questions"

    def view_sessions_link(self, obj):
        count = getattr(obj, "sessions_count", None)
        if count is None:
            count = obj.sessions.count()
        url = reverse("admin:quizzes_quizsession_changelist") + f"?quiz__id__exact={obj.id}"
        return format_html('<a href="{}">View {} Sessions</a>', url, count)

    view_sessions_link.short_description = "Sessions"
    view_sessions_link.admin_order_field = "sessions_count"


@admin.register(SharedQuiz)
class SharedQuizAdmin(ModelAdmin):
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


@admin.register(Comment)
class CommentAdmin(ModelAdmin):
    list_display = ["quiz", "question", "author", "is_deleted", "created_at"]
    list_filter = ["is_deleted", "created_at"]
    search_fields = ["content", "quiz__title", "question__text", "author__email"]
    autocomplete_fields = ["author", "parent", "quiz", "question"]
    readonly_fields = ["created_at", "updated_at", "deleted_at"]


@admin.register(QuestionChangeSuggestion)
class QuestionChangeSuggestionAdmin(ModelAdmin):
    list_display = ["question", "status", "resolved_by", "created_at", "resolved_at"]
    list_filter = ["status", "created_at", "resolved_at"]
    search_fields = ["question__text", "comment__content", "comment__quiz__title"]
    autocomplete_fields = ["comment", "question", "resolved_by"]
    readonly_fields = ["created_at", "updated_at", "resolved_at"]


@admin.register(Folder)
class FolderAdmin(ModelAdmin):
    search_fields = ["name", "owner__first_name", "owner__last_name", "owner__email"]
    autocomplete_fields = ["owner", "parent"]
