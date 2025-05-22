from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    QuizViewSet,
    SharedQuizViewSet,
    QuizCollaboratorViewSet,
    random_question_for_user,
    last_used_quizzes,
    quiz_metadata,
    quiz_progress,
    import_quiz_from_link,
)

router = DefaultRouter()
router.register(r"quizzes", QuizViewSet)
router.register(r"shared-quizzes", SharedQuizViewSet)
router.register(r"collaborators", QuizCollaboratorViewSet, basename="collaborator")

urlpatterns = [
    path("", include(router.urls)),
    path("random-question/", random_question_for_user, name="random-question"),
    path("last-used/", last_used_quizzes, name="last-used-quizzes"),
    path("quiz/<uuid:quiz_id>/metadata/", quiz_metadata, name="quiz-metadata"),
    path("quiz/<uuid:quiz_id>/progress/", quiz_progress, name="quiz-progress"),
    path("import-from-link/", import_quiz_from_link, name="import-from-link"),
]
