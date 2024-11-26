"""
URL configuration for testownik_core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from grades import views as grades_views
from quizzes import views as quizzes_views
from users import views as users_views

urlpatterns = [
    path("", users_views.index, name="index"),
    path("admin/login/", users_views.admin_login, name="admin_login"),
    path("admin/", admin.site.urls, name="admin"),
    path("login/", users_views.login_view, name="login_view"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("login/usos/", users_views.login_usos, name="login_usos"),
    path("authorize/", users_views.authorize, name="authorize"),
    path("profile/", users_views.profile, name="profile"),
    path("api/settings/", users_views.api_settings, name="api_settings"),
    path(
        "api/refresh-user-data/",
        users_views.refresh_user_data,
        name="refresh_user_data",
    ),
    path("api/get-grades/", grades_views.get_grades, name="get_grades"),
    path("grades/", include("grades.urls")),
    path("quizzes/", include("quizzes.urls")),
    path("api/quiz/<uuid:quiz_id>/", quizzes_views.quiz_api, name="quiz_api"),
    path(
        "api/quiz/<uuid:quiz_id>/progress/",
        quizzes_views.quiz_progress_api,
        name="progress_api",
    ),
    path(
        "api/random-question-for-user/",
        quizzes_views.random_question_for_user,
        name="random_question_for_user",
    ),
]
