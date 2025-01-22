from django.urls import path

from quizzes import views

app_name = "quizzes"
urlpatterns = [
    path("<uuid:quiz_id>/", views.quiz, name="quiz"),
]
