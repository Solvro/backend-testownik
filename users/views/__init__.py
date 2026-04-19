from .admin import admin_login
from .auth_tokens import CustomTokenObtainPairView, CustomTokenRefreshView
from .email_auth import GenerateOtpView, LoginLinkView, LoginOtpView
from .oauth import (
    SolvroAuthorizeView,
    SolvroLoginView,
    UsosAuthorizeView,
    UsosLoginView,
    oauth,
    update_user_data_from_usos,
)
from .user_management import (
    CurrentUserView,
    DeleteAccountView,
    GuestCreateView,
    SettingsViewSet,
    StudyGroupViewSet,
    UserViewSet,
)
from .utils import (
    ALLOW_PREVIEW_ENVIRONMENTS,
    ALLOWED_REDIRECT_ORIGINS,
    PREVIEW_ORIGIN_REGEXES,
    is_safe_redirect_url,
)

__all__ = [
    "ALLOW_PREVIEW_ENVIRONMENTS",
    "ALLOWED_REDIRECT_ORIGINS",
    "CurrentUserView",
    "CustomTokenObtainPairView",
    "CustomTokenRefreshView",
    "DeleteAccountView",
    "GenerateOtpView",
    "GuestCreateView",
    "LoginLinkView",
    "LoginOtpView",
    "PREVIEW_ORIGIN_REGEXES",
    "SettingsViewSet",
    "SolvroAuthorizeView",
    "SolvroLoginView",
    "StudyGroupViewSet",
    "UsosAuthorizeView",
    "UsosLoginView",
    "UserViewSet",
    "admin_login",
    "is_safe_redirect_url",
    "oauth",
    "update_user_data_from_usos",
]
