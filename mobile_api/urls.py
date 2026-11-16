from django.urls import path

from . import views
from .quiz_create import MobileQuizCreateView

urlpatterns = [
    path("auth/otp/", views.MobileOTPView.as_view()),
    path("auth/refresh/", views.MobileRefreshView.as_view()),
    path("auth/guest/", views.MobileGuestView.as_view()),
    path("auth/web-session/", views.MobileWebSessionView.as_view()),
    path("auth/logout/", views.MobileLogoutView.as_view()),
    path("auth/start/", views.MobileStartView.as_view()),
    path("auth/browser/<uuid:attempt_id>/", views.mobile_browser),
    path("auth/complete/", views.mobile_complete),
    path("auth/exchange/", views.MobileExchangeView.as_view()),
    path("quizzes/<uuid:quiz_id>/answer/", views.MobileAnswerView.as_view()),
    path("quizzes/", MobileQuizCreateView.as_view()),
    path("account/deletion/", views.MobileAccountDeletionView.as_view()),
]
