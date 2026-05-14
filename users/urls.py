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
    path(
        "settings/",
        views.SettingsViewSet.as_view(
            {
                "get": "retrieve",
                "put": "update",
                "patch": "partial_update",
            }
        ),
        name="api_settings",
    ),
    path(
        "user/delete-account/",
        views.DeleteAccountView.as_view(),
        name="api_delete_account",
    ),
    path("admin/login/", views.admin_login, name="admin_login"),
    path("login/usos/", views.UsosLoginView.as_view(), name="login_usos"),
    path("login/", views.SolvroLoginView.as_view(), name="login"),
    path("authorize/", views.SolvroAuthorizeView.as_view(), name="authorize"),
    path("authorize/usos/", views.UsosAuthorizeView.as_view(), name="authorize_usos"),
    path("guest/create/", views.GuestCreateView.as_view(), name="guest_create"),
]

urlpatterns += router.urls
