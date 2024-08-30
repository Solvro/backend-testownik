from django.urls import path

from quizzes import views

app_name = "quizzes"
urlpatterns = [
    path("", views.index, name="index"),
    path("import/", views.import_quiz, name="import_quiz"),
    path("import-old/", views.import_quiz_old, name="import_quiz_old"),
    path("<uuid:quiz_id>/", views.quiz, name="quiz"),
    path("<uuid:quiz_id>/edit/", views.edit_quiz, name="edit_quiz"),
    path("quizzes/", views.quizzes, name="quizzes"),
]
