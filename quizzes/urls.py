from django.urls import include, path
from rest_framework.routers import DefaultRouter

from quizzes.views import (
    ImportQuizFromLinkView,
    LastUsedQuizzesView,
    QuizMetadataView,
    QuizProgressView,
    QuizViewSet,
    RandomQuestionView,
    ReportQuestionIssueView,
    SearchQuizzesView,
    SharedQuizViewSet,
)

router = DefaultRouter()
router.register("quizzes", QuizViewSet)
router.register("shared-quizzes", SharedQuizViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("random-question/", RandomQuestionView.as_view(), name="random-question"),
    path("last-used-quizzes/", LastUsedQuizzesView.as_view(), name="last-used-quizzes"),
    path(
        "quiz/<uuid:quiz_id>/metadata/",
        QuizMetadataView.as_view(),
        name="quiz-metadata",
    ),
    path(
        "quiz/<uuid:quiz_id>/progress/",
        QuizProgressView.as_view(),
        name="quiz-progress",
    ),
    path(
        "import-from-link/", ImportQuizFromLinkView.as_view(), name="import-from-link"
    ),
    path(
        "report-question-issue/",
        ReportQuestionIssueView.as_view(),
        name="report-question-issue",
    ),
    path("search-quizzes/", SearchQuizzesView.as_view(), name="search-quizzes"),
]
