from django.urls import include, path
from rest_framework.routers import DefaultRouter

from quizzes.views import (
    FolderViewSet,
    LastUsedQuizzesView,
    LibraryView,
    QuizViewSet,
    RandomQuestionView,
    ReportQuestionIssueView,
    SearchQuizzesView,
    SharedQuizViewSet,
)

router = DefaultRouter()
router.register("quizzes", QuizViewSet)
router.register("shared-quizzes", SharedQuizViewSet)
router.register("folders", FolderViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("random-question/", RandomQuestionView.as_view(), name="random-question"),
    path("last-used-quizzes/", LastUsedQuizzesView.as_view(), name="last-used-quizzes"),
    path("library/", LibraryView.as_view(), name="library-root"),
    path("library/<uuid:folder_id>/", LibraryView.as_view(), name="library-folder"),
    path(
        "report-question-issue/",
        ReportQuestionIssueView.as_view(),
        name="report-question-issue",
    ),
    path("search-quizzes/", SearchQuizzesView.as_view(), name="search-quizzes"),
]
