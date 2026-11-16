"""Authorize guest upgrades without treating a public account UUID as a secret."""

import secrets
import time
from uuid import UUID

from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

from users.models import AccountType

_SESSION_KEY = "guest_migration_flows"
_FLOW_LIFETIME = 15 * 60


def authorize_guest_migration(request, guest_id, *, allow_cookie=False):
    """Require the guest's bearer; OAuth entry points can also use its browser cookie.

    Email login deliberately does not authenticate cookies: those views are exempt
    from CSRF, and accepting a cookie would let an attacker supply their own OTP.
    """
    if not guest_id:
        return ""
    try:
        requested_id = UUID(str(guest_id))
        authenticator = JWTAuthentication()
        header = authenticator.get_header(request)
        raw = authenticator.get_raw_token(header) if header is not None else None
        if header is not None and raw is None:
            raise PermissionDenied("A valid guest bearer is required.")
        if header is None and allow_cookie:
            raw = request.COOKIES.get("access_token")
        if not raw:
            raise PermissionDenied("Guest migration requires the guest's access token.")
        token = authenticator.get_validated_token(raw)
        guest = authenticator.get_user(token)
        if (
            guest.pk != requested_id
            or guest.account_type != AccountType.GUEST
            or not guest.is_active
            or guest.is_banned
            or token.get("mobile_embed")
        ):
            raise PermissionDenied("The guest credential does not authorize this migration.")
        return str(guest.pk)
    except (ValueError, TypeError, AuthenticationFailed) as exc:
        raise PermissionDenied("A valid matching guest credential is required.") from exc


def bind_oauth_guest_migration(request, guest_id):
    """Bind an already verified guest to one browser OAuth flow, not callback input."""
    if not guest_id:
        return ""
    now = time.time()
    flows = {key: value for key, value in request.session.get(_SESSION_KEY, {}).items() if value["expires"] > now}
    # Keep concurrent login attempts bounded without replacing the newest flow.
    flows = dict(list(flows.items())[-7:])
    nonce = secrets.token_urlsafe(32)
    flows[nonce] = {"guest_id": guest_id, "expires": now + _FLOW_LIFETIME}
    request.session[_SESSION_KEY] = flows
    return nonce


def validate_oauth_guest_migration(request):
    """Require both the browser's verified guest and its flow-bound grant."""
    nonce = request.GET.get("guest_migration", "")
    if request.GET.get("guest_id"):
        raise PermissionDenied("Restart sign-in to securely transfer this guest account.")
    if not nonce:
        return ""
    flow = request.session.get(_SESSION_KEY, {}).get(nonce)
    if not flow or flow["expires"] <= time.time():
        raise PermissionDenied("Guest sign-in has expired. Restart sign-in to transfer your data.")
    return authorize_guest_migration(request, flow["guest_id"], allow_cookie=True)


def consume_oauth_guest_migration(request):
    """Consume only after provider state/request-token validation has succeeded."""
    guest_id = validate_oauth_guest_migration(request)
    if guest_id:
        flows = request.session.get(_SESSION_KEY, {})
        flows.pop(request.GET["guest_migration"], None)
        request.session[_SESSION_KEY] = flows
    return guest_id
