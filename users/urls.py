from django.urls import path
from rest_framework.routers import DefaultRouter

from users import views

router = DefaultRouter()
router.register("users", views.UserViewSet)
router.register("study-groups", views.StudyGroupViewSet)

urlpatterns = [
    path("generate-otp/", views.GenerateOtpView.as_view(), name="generate_otp"),
    path("login-link/", views.LoginLinkView.as_view(), name="login_link"),
    path("login-otp/", views.LoginOtpView.as_view(), name="login_otp"),
    path("user/", views.CurrentUserView.as_view(), name="api_current_user"),
    path("settings/", views.SettingsView.as_view(), name="api_settings"),
    path(
        "user/delete-account/",
        views.DeleteAccountView.as_view(),
        name="api_delete_account",
    ),
    path("admin/login/", views.admin_login, name="admin_login"),
    path("login/usos/", views.login_usos, name="login_usos"),
    path("authorize/", views.authorize, name="authorize"),
]

urlpatterns += router.urls
