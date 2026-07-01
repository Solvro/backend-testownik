import contextlib
import uuid

from django.contrib import admin
from django.db.models import Q
from unfold.admin import ModelAdmin, TabularInline

from wrapped.models import WrappedReport, WrappedTopQuiz


class WrappedTopQuizInline(TabularInline):
    model = WrappedTopQuiz
    extra = 0


@admin.register(WrappedReport)
class WrappedReportAdmin(ModelAdmin):
    list_display = (
        "term",
        "user",
        "is_global",
        "composite_score",
        "percentile",
        "total_answers",
        "generated_at",
    )
    list_filter = ("term", "is_global")
    list_select_related = ("user", "term")
    search_fields = (
        "user__first_name",
        "user__last_name",
        "user__email",
        "user__student_number",
        "term__id",
        "term__name",
    )
    autocomplete_fields = ("user", "term")
    readonly_fields = ("generated_at",)
    ordering = ("-generated_at",)
    inlines = [WrappedTopQuizInline]

    def get_search_results(self, request, queryset, search_term):
        base_queryset = queryset
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        term = search_term.strip()
        if not term:
            return queryset, may_have_duplicates

        exact_user = Q()
        with contextlib.suppress(ValueError):
            exact_user |= Q(user_id=uuid.UUID(term))

        if term.isdecimal():
            exact_user |= Q(user__usos_id=int(term))

        if exact_user:
            queryset = queryset | base_queryset.filter(exact_user)
            may_have_duplicates = True

        return queryset, may_have_duplicates
