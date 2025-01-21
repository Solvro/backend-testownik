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
from rest_framework import routers
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from grades import views as grades_views
from quizzes import views as quizzes_views
from users import views as users_views
from users.views import api_current_user

router = routers.DefaultRouter()
router.register(r"users", users_views.UserViewSet)
router.register(r"study-groups", users_views.StudyGroupViewSet)
router.register(r"quizzes", quizzes_views.QuizViewSet)
router.register(r"shared-quizzes", quizzes_views.SharedQuizViewSet)


urlpatterns = [
    path("", users_views.index, name="index"),
    path("admin/login/", users_views.admin_login, name="admin_login"),
    path("admin/", admin.site.urls, name="admin"),
    # path("login/", users_views.login_view, name="login_view"),
    # path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("login/usos/", users_views.login_usos, name="login_usos"),
    path("authorize/", users_views.authorize, name="authorize"),
    # path("profile/", users_views.profile, name="profile"),
    # path(
    #     "api/refresh-user-data/",
    #     users_views.refresh_user_data,
    #     name="refresh_user_data",
    # ),
    path("api/grades/", grades_views.get_grades, name="get_grades"),
    path("quizzes/", include("quizzes.urls")),
    path(
        "api/legacy/quiz/<uuid:quiz_id>/",
        quizzes_views.quiz_legacy_api,
        name="quiz_legacy_api",
    ),
    # path(
    #     "api/legacy/quiz/<uuid:quiz_id>/progress/",
    #     quizzes_views.quiz_progress_legacy_api,
    #     name="progress_legacy_api",
    # ),
    # path(
    #     "api/random-question-for-user/",
    #     quizzes_views.random_question_for_user,
    #     name="random_question_for_user",
    # ),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/", include(router.urls)),
    path("api/user/", api_current_user, name="api_current_user"),
    path(
        "api/random-question/",
        quizzes_views.api_random_question_for_user,
        name="api_random_question_for_user",
    ),
    path("api/settings/", users_views.api_settings, name="api_settings"),
    path(
        "api/last-used-quizzes/",
        quizzes_views.api_last_used_quizzes,
        name="api_last_used_quizzes",
    ),
    path(
        "api/search-quizzes/",
        quizzes_views.api_search_quizzes,
        name="api_search_quizzes",
    ),
    path(
        "api/quiz-metadata/<uuid:quiz_id>/",
        quizzes_views.quiz_metadata_api,
        name="api_quiz_metadata",
    ),
    path(
        "api/import-quiz-from-link/",
        quizzes_views.import_quiz_from_link_api,
        name="import_quiz_from_link_api",
    ),
    path(
        "api/report-quiz-error/",
        quizzes_views.report_question_issue_api,
        name="report_question_issue_api",
    ),
    path(
        "api/quiz-progress/<uuid:quiz_id>/",
        quizzes_views.quiz_progress_api,
        name="quiz_progress_api",
    ),
]
