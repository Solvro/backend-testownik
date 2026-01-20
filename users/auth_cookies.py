from django.conf import settings
from django.http import HttpResponse


def set_jwt_cookies(
    response: HttpResponse,
    access_token: str,
    refresh_token: str,
    access_max_age: int = 3600,  # 1 hour
    refresh_max_age: int = 30 * 24 * 60 * 60,  # 30 days
) -> HttpResponse:
    """Set JWT tokens as cookies on the response."""

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
