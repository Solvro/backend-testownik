from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse


def set_jwt_cookies(
    response: HttpResponse,
    access_token: str,
    refresh_token: str,
    access_max_age: int | None = None,
    refresh_max_age: int | None = None,
) -> HttpResponse:
    """Set JWT tokens as cookies on the response."""
    simple_jwt = getattr(settings, "SIMPLE_JWT", {})

    if access_max_age is None:
        access_lifetime = simple_jwt.get("ACCESS_TOKEN_LIFETIME")
        access_max_age = int(access_lifetime.total_seconds()) if isinstance(access_lifetime, timedelta) else 3600

    if refresh_max_age is None:
        refresh_lifetime = simple_jwt.get("REFRESH_TOKEN_LIFETIME")
        refresh_max_age = (
            int(refresh_lifetime.total_seconds()) if isinstance(refresh_lifetime, timedelta) else 3600 * 24 * 7
        )

    # Access token - readable by client JavaScript
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=access_max_age,
        secure=settings.JWT_COOKIE_SECURE,
        httponly=False,  # Client needs to read this
        samesite=settings.JWT_COOKIE_SAMESITE,
        domain=settings.JWT_COOKIE_DOMAIN,
        path="/",
    )

    # Refresh token - httpOnly for security
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=refresh_max_age,
        secure=settings.JWT_COOKIE_SECURE,
        httponly=True,  # Only accessible to server
        samesite=settings.JWT_COOKIE_SAMESITE,
        domain=settings.JWT_COOKIE_DOMAIN,
        path="/",
    )

    return response
