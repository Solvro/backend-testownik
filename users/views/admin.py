import logging

from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import reverse

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

    usos_login_url = reverse("login_usos") + f"?redirect={next_url}"
    solvro_login_url = reverse("login") + f"?redirect={next_url}"

    context = {
        **admin.site.each_context(request),
        "next": next_url,
        "username": request.user,
        "usos_login_url": usos_login_url,
        "solvro_login_url": solvro_login_url,
        "usos_login_url_confirm": usos_login_url + "&confirm_user=true",
        "solvro_login_url_confirm": solvro_login_url + "&confirm_user=true",
    }

    return render(request, "users/admin_login.html", context)
