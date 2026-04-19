import logging

from django.contrib import messages
from django.shortcuts import redirect, render

from .utils import is_safe_redirect_url

logger = logging.getLogger(__name__)


def admin_login(request):
    next_url = request.GET.get("next", "admin:index")
    if not is_safe_redirect_url(next_url, request):
        logger.warning("Blocked unsafe redirect URL in admin_login: %s", next_url)
        messages.error(request, "Unsafe redirect URL, defaulting to admin index")
        next_url = "admin:index"
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect(next_url)
    return render(request, "users/admin_login.html", {"next": next_url, "username": request.user})
