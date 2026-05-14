"""Shared helpers for auth views: OAuth param parsing, JWT response building, login finalization."""

import logging
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.contrib.auth import alogin as async_auth_login
from django.contrib.auth import login as auth_login
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, resolve_url
from rest_framework.response import Response

from users.auth_cookies import set_jwt_cookies
from users.serializers import UserTokenObtainPairSerializer
from users.services import migrate_guest_to_user

from .utils import add_query_params, get_safe_redirect_url, remove_query_params

logger = logging.getLogger(__name__)


@dataclass
class OAuthLoginParams:
    jwt: bool
    redirect_url: str
    raw_redirect_url: str
    guest_id: str
    confirm_user: bool


def parse_oauth_login_params(request) -> OAuthLoginParams:
    """Parse the common OAuth login query params shared by Solvro and USOS login views."""
    return OAuthLoginParams(
        jwt=request.GET.get("jwt", "false") == "true",
        redirect_url=get_safe_redirect_url(request.GET.get("redirect", ""), request, default=""),
        raw_redirect_url=request.GET.get("redirect", ""),
        guest_id=request.GET.get("guest_id", ""),
        confirm_user=request.GET.get("confirm_user", "false") == "true",
    )


def validate_login_params(params: OAuthLoginParams):
    """Validate OAuth login params. Returns an HttpResponse on error, or None if OK."""
    if params.raw_redirect_url and not params.redirect_url:
        return HttpResponseBadRequest("Invalid redirect URL")
    if params.jwt and not params.redirect_url:
        return HttpResponseForbidden("Redirect URL must be provided when using JWT")
    return None


def build_callback_params(params: OAuthLoginParams) -> dict:
    """Build the OAuth callback query params from login params."""
    callback_params = {"jwt": str(params.jwt).lower()}
    if params.redirect_url:
        callback_params["redirect"] = params.redirect_url
    if params.guest_id:
        callback_params["guest_id"] = params.guest_id
    return callback_params


def set_jwt_cookies_for_user(response, user):
    """Issue a fresh JWT pair for `user` and attach both tokens as cookies on `response`."""
    refresh = UserTokenObtainPairSerializer.get_token(user)
    set_jwt_cookies(response, str(refresh.access_token), str(refresh))
    return response


async def aset_jwt_cookies_for_user(response, user):
    refresh = await sync_to_async(UserTokenObtainPairSerializer.get_token)(user)
    set_jwt_cookies(response, str(refresh.access_token), str(refresh))
    return response


def jwt_login_response(user, *, body=None, status=200) -> Response:
    """Build a DRF Response with JWT cookies set for `user`."""
    response = Response(body if body is not None else {"message": "Login successful"}, status=status)
    return set_jwt_cookies_for_user(response, user)


def _banned_redirect(redirect_url: str, user):
    auth_params = {"error": "user_banned"}
    if user.ban_reason:
        auth_params["ban_reason"] = user.ban_reason
    return redirect(add_query_params(redirect_url, auth_params))


def handle_oauth_login_result(request, user, *, jwt: bool, redirect_url: str, guest_id: str = ""):
    """Finalize a sync OAuth login: ban check, guest migration, JWT cookies or session login."""
    safe_redirect_url = get_safe_redirect_url(redirect_url, request, default=resolve_url("index"))

    if user.is_banned:
        logger.warning("Banned user attempted login. Email: %s", user.email)
        if jwt:
            return _banned_redirect(safe_redirect_url, user)
        messages.error(
            request,
            f"Twoje konto zostało zablokowane: {user.ban_reason or 'Brak powodu'}",
        )
        return redirect(safe_redirect_url)

    if guest_id:
        migrate_guest_to_user(guest_id, user)

    if jwt:
        response = redirect(remove_query_params(safe_redirect_url, ["error"]))
        return set_jwt_cookies_for_user(response, user)

    auth_login(request, user)
    return redirect(safe_redirect_url)


async def ahandle_oauth_login_result(request, user, *, jwt: bool, redirect_url: str, guest_id: str = ""):
    """Async variant of handle_oauth_login_result for USOS flow."""
    safe_redirect_url = get_safe_redirect_url(redirect_url, request, default=resolve_url("index"))

    if user.is_banned:
        logger.warning("Banned user attempted login. Email: %s", user.email)
        if jwt:
            return _banned_redirect(safe_redirect_url, user)
        messages.error(
            request,
            f"Twoje konto zostało zablokowane: {user.ban_reason or 'Brak powodu'}",
        )
        return redirect(safe_redirect_url)

    if guest_id:
        await sync_to_async(migrate_guest_to_user)(guest_id, user)

    if jwt:
        response = redirect(remove_query_params(safe_redirect_url, ["error"]))
        return await aset_jwt_cookies_for_user(response, user)

    await async_auth_login(request, user)
    return redirect(safe_redirect_url)


def resolve_callback_redirect_url(request):
    """Resolve the `redirect` query param to a safe URL, defaulting to the `index` route."""
    return get_safe_redirect_url(
        request.GET.get("redirect", resolve_url("index")),
        request,
        default=resolve_url("index"),
    )
