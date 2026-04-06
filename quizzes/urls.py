from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_nested.routers import NestedDefaultRouter

from quizzes.views import (
    CommentViewSet,
    FolderViewSet,
    LastUsedQuizzesView,
    LibraryView,
    QuestionViewSet,
    QuizRatingViewSet,
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
router.register("questions", QuestionViewSet)
router.register("quiz-ratings", QuizRatingViewSet)

quizzes_router = NestedDefaultRouter(router, "quizzes", lookup="quiz")
quizzes_router.register("comments", CommentViewSet, basename="quiz-comments")

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
    path("", include(quizzes_router.urls)),
]
