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
from django.urls import include, path
from rest_framework import routers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from alerts.views import AlertViewSet
from feedback import views as feedback_views
from grades import views as grades_views
from quizzes import views as quizzes_views
from users import views as users_views
from users.views import current_user


@api_view(["GET"])
@permission_classes([AllowAny])
def status(request):
    return Response({"status": "ok"})


router = routers.DefaultRouter()
router.register(r"users", users_views.UserViewSet)
router.register(r"study-groups", users_views.StudyGroupViewSet)
router.register(r"quizzes", quizzes_views.QuizViewSet)
router.register(r"shared-quizzes", quizzes_views.SharedQuizViewSet)
router.register(r"alerts", AlertViewSet)

urlpatterns = [
    # Status
    path("status/", status, name="status"),
    # Admin
    path("admin/login/", users_views.admin_login, name="admin_login"),
    path("admin/", admin.site.urls, name="admin"),
    # USOS login
    path("login/usos/", users_views.login_usos, name="login_usos"),
    path("authorize/", users_views.authorize, name="authorize"),
    # API authentication
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("generate-otp/", users_views.generate_otp, name="generate_otp"),
    path("login-link/", users_views.login_link, name="login_link"),
    path("login-otp/", users_views.login_otp, name="login_otp"),
    # API
    path("", include(router.urls)),
    path("user/", current_user, name="api_current_user"),
    path("settings/", users_views.settings, name="api_settings"),
    path(
        "random-question/",
        quizzes_views.random_question_for_user,
        name="api_random_question_for_user",
    ),
    path(
        "last-used-quizzes/",
        quizzes_views.last_used_quizzes,
        name="api_last_used_quizzes",
    ),
    path(
        "quiz-progress/<uuid:quiz_id>/",
        quizzes_views.quiz_progress,
        name="quiz_progress_api",
    ),
    path(
        "search-quizzes/",
        quizzes_views.search_quizzes,
        name="api_search_quizzes",
    ),
    path(
        "quiz-metadata/<uuid:quiz_id>/",
        quizzes_views.quiz_metadata,
        name="api_quiz_metadata",
    ),
    path(
        "import-quiz-from-link/",
        quizzes_views.import_quiz_from_link,
        name="import_quiz_from_link_api",
    ),
    path(
        "report-quiz-error/",
        quizzes_views.report_question_issue,
        name="report_question_issue_api",
    ),
    path("grades/", grades_views.get_grades, name="get_grades"),
    path(
        "feedback/send",
        feedback_views.feedback_add,
        name="feedback_add_api",
    ),
]

# Admin site settings
admin.site.site_url = "https://testownik.solvro.pl/"
admin.site.site_header = "Testownik Solvro"
