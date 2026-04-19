import logging
import os
from asyncio import CancelledError, sleep

import dotenv
from adrf.views import APIView as AsyncAPIView
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from usos_api import USOSAPIException, USOSClient
from usos_api.models import StaffStatus, StudentStatus

from testownik_core.settings import oauth
from users.models import AccountType, StudyGroup, Term, User

from .auth_helpers import (
    ahandle_oauth_login_result,
    build_callback_params,
    handle_oauth_login_result,
    parse_oauth_login_params,
    resolve_callback_redirect_url,
    validate_login_params,
)
from .utils import (
    add_query_params,
    build_oauth_callback_url,
)

dotenv.load_dotenv()

logger = logging.getLogger(__name__)

_COMMON_LOGIN_PARAMETERS = [
    OpenApiParameter(
        "jwt",
        OpenApiTypes.BOOL,
        OpenApiParameter.QUERY,
        description=(
            "If true, the authorize callback returns JWT tokens via cookies instead of creating a session. "
            "Requires `redirect` to be set."
        ),
        default=False,
    ),
    OpenApiParameter(
        "redirect",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        description="URL to redirect the user to after successful authorization.",
    ),
    OpenApiParameter(
        "confirm_user",
        OpenApiTypes.BOOL,
        OpenApiParameter.QUERY,
        description="If true, forces the OAuth provider to re-prompt the user for credentials.",
        default=False,
    ),
    OpenApiParameter(
        "guest_id",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        description="Guest account ID to migrate to the authenticated user.",
    ),
]

_COMMON_CALLBACK_PARAMETERS = [
    OpenApiParameter(
        "jwt",
        OpenApiTypes.BOOL,
        OpenApiParameter.QUERY,
        description="If true, set JWT tokens as cookies instead of creating a session.",
        default=False,
    ),
    OpenApiParameter(
        "redirect",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        description="URL to redirect to after authorization. Defaults to index.",
    ),
    OpenApiParameter(
        "guest_id",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        description="Guest account ID to migrate to the authenticated user.",
    ),
]


class SolvroLoginView(APIView):
    """Initiate Solvro OAuth login flow. Redirects the browser to the Solvro auth provider."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="Solvro OAuth - initiate login",
        description=(
            "Redirects the user to the Solvro OAuth provider. "
            "After the user authenticates, the provider redirects back to `/api/authorize/`."
        ),
        parameters=_COMMON_LOGIN_PARAMETERS,
        responses={
            302: OpenApiResponse(description="Redirect to Solvro OAuth provider."),
            400: OpenApiResponse(description="Invalid redirect URL."),
        },
        tags=["Authentication"],
    )
    def get(self, request):
        params = parse_oauth_login_params(request)
        error_response = validate_login_params(params)
        if error_response is not None:
            return error_response

        callback_url = add_query_params(
            request.build_absolute_uri("/api/authorize/"),
            build_callback_params(params),
        )

        additional_params = {"prompt": "login"} if params.confirm_user else {}
        return oauth.create_client("solvro-auth").authorize_redirect(request, callback_url, **additional_params)


class UsosLoginView(AsyncAPIView):
    """Initiate USOS OAuth login flow. Redirects the browser to USOS for authentication."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="USOS OAuth - initiate login",
        description=(
            "Redirects the user to the USOS OAuth provider. "
            "After the user authenticates, the provider redirects back to `/api/authorize/usos/`. "
            "Retries up to 3 times on USOS connection failure."
        ),
        parameters=_COMMON_LOGIN_PARAMETERS,
        responses={
            302: OpenApiResponse(
                description="Redirect to USOS OAuth provider, or redirect with `?error=usos_unavailable` on failure."
            ),
            400: OpenApiResponse(description="Invalid redirect URL."),
            403: OpenApiResponse(description="`jwt=true` but no `redirect` URL provided."),
            404: OpenApiResponse(description="Not found."),
        },
        tags=["Authentication"],
    )
    async def get(self, request):
        params = parse_oauth_login_params(request)
        error_response = validate_login_params(params, require_redirect_for_jwt=True)
        if error_response is not None:
            return error_response

        callback_url = build_oauth_callback_url(request, "/api/authorize/usos/", build_callback_params(params))

        usos_key = os.getenv("USOS_CONSUMER_KEY")
        usos_secret = os.getenv("USOS_CONSUMER_SECRET")

        if not usos_key or not usos_secret:
            logger.error(
                "USOS credentials not configured. USOS_CONSUMER_KEY=%s, USOS_CONSUMER_SECRET=%s",
                "<set>" if usos_key else "<missing>",
                "<set>" if usos_secret else "<missing>",
            )
            return redirect(add_query_params(params.redirect_url or "index", {"error": "usos_unavailable"}))

        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                async with USOSClient(
                    "https://apps.usos.pwr.edu.pl/",
                    usos_key,
                    usos_secret,
                    trust_env=True,
                ) as client:
                    client.set_scopes(["offline_access", "studies", "email", "photo", "grades"])
                    authorization_url = await client.get_authorization_url(callback_url, params.confirm_user)
                    request_token, request_token_secret = client.connection.auth_manager.get_request_token()
                    await request.session.aset(f"request_token_{request_token}", request_token_secret)
                    request.session.modified = True

                return redirect(authorization_url)

            except Exception as e:
                if isinstance(e, CancelledError):
                    raise

                logger.error(
                    "USOS login attempt %d/%d failed. Error: %s [%s]. Callback: %s, JWT: %s, Redirect: %s. ",
                    attempt + 1,
                    max_retries,
                    str(e),
                    type(e).__name__,
                    callback_url,
                    params.jwt,
                    params.redirect_url,
                    exc_info=True,
                )

                if attempt < max_retries - 1:
                    await sleep(retry_delay)
                    continue

                return redirect(add_query_params(params.redirect_url or "index", {"error": "usos_unavailable"}))

        return redirect(add_query_params(params.redirect_url or "index", {"error": "usos_unavailable"}))


class SolvroAuthorizeView(APIView):
    """Solvro OAuth callback. Exchanges the authorization code for user profile and logs in."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="Solvro OAuth - authorization callback",
        description=(
            "OAuth callback hit by the Solvro auth provider after user authentication. "
            "Exchanges the authorization code for an access token, fetches the user profile, "
            "and either creates a session or sets JWT cookies (when `jwt=true`). "
            "Redirects to `redirect` URL on completion."
        ),
        parameters=_COMMON_CALLBACK_PARAMETERS,
        responses={
            302: OpenApiResponse(
                description=(
                    "Redirect to the redirect URL with JWT cookies set (if `jwt=true`), "
                    "or with `?error=no_email` if the user profile has no email, "
                    "or with `?error=user_banned&ban_reason=...` if the user is banned."
                )
            ),
        },
        tags=["Authentication"],
    )
    def get(self, request):
        try:
            token = oauth.create_client("solvro-auth").authorize_access_token(request)
        except Exception as e:
            logger.error("Failed to obtain Solvro auth access token: %s", str(e), exc_info=True)
            raise

        try:
            resp = oauth.create_client("solvro-auth").get(
                "https://auth.solvro.pl/realms/solvro/protocol/openid-connect/userinfo",
                token=token,
            )
            resp.raise_for_status()
            profile = resp.json()
        except Exception as e:
            logger.error("Failed to retrieve Solvro user profile: %s", str(e), exc_info=True)
            raise

        redirect_url = resolve_callback_redirect_url(request)
        jwt = request.GET.get("jwt", "false") == "true"
        guest_id = request.GET.get("guest_id", "")

        if not profile.get("email"):
            logger.error(
                "Solvro user profile missing email. Profile keys: %s",
                list(profile.keys()),
            )
            if jwt:
                return redirect(add_query_params(redirect_url, {"error": "no_email"}))
            messages.error(request, "Brak adresu email w profilu użytkownika.")
            return redirect(redirect_url)

        user, _ = User.objects.update_or_create(
            email=profile["email"],
            defaults={
                "photo_url": f"https://api.dicebear.com/9.x/adventurer/svg?seed={profile['email']}",
            },
            create_defaults={
                "account_type": AccountType.EMAIL,
                "photo_url": f"https://api.dicebear.com/9.x/adventurer/svg?seed={profile['email']}",
            },
        )

        return handle_oauth_login_result(request, user, jwt=jwt, redirect_url=redirect_url, guest_id=guest_id)


class UsosAuthorizeView(AsyncAPIView):
    """USOS OAuth callback. Exchanges the request token for user data and logs in."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="USOS OAuth - authorization callback",
        description=(
            "OAuth callback hit by USOS after user authentication. "
            "Exchanges the request token for an access token, fetches the user profile from USOS, "
            "and either creates a session or sets JWT cookies (when `jwt=true`). "
            "Redirects to `redirect` URL on completion. "
            "On failure, retries once automatically before returning an error."
        ),
        parameters=[
            *_COMMON_CALLBACK_PARAMETERS,
            OpenApiParameter(
                "oauth_verifier",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="OAuth verifier provided by USOS.",
            ),
            OpenApiParameter(
                "oauth_token",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="OAuth request token provided by USOS.",
            ),
            OpenApiParameter(
                "retry",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Internal retry flag. Set to '1' on automatic retry.",
            ),
        ],
        responses={
            302: OpenApiResponse(
                description=(
                    "Redirect to `redirect` URL on success, or with error query params: "
                    "`?error=invalid_token` (session expired), "
                    "`?error=authorization_failed` (USOS API error), "
                    "`?error=not_student` (user is not an active student), "
                    "`?error=user_banned&ban_reason=...` (user is banned)."
                )
            ),
            403: OpenApiResponse(description="Authorization failed and retry exhausted (non-JWT mode)."),
            404: OpenApiResponse(description="Not found."),
        },
        tags=["Authentication"],
    )
    async def get(self, request):
        redirect_url = resolve_callback_redirect_url(request)
        jwt = request.GET.get("jwt", "false") == "true"
        guest_id = request.GET.get("guest_id", "")

        async with USOSClient(
            "https://apps.usos.pwr.edu.pl/",
            os.getenv("USOS_CONSUMER_KEY"),
            os.getenv("USOS_CONSUMER_SECRET"),
            trust_env=True,
        ) as client:
            verifier = request.GET.get("oauth_verifier")
            request_token = request.GET.get("oauth_token")

            request_token_secret = await request.session.apop(f"request_token_{request_token}", None)
            if not request_token_secret:
                logger.error(
                    "USOS request token secret not found in session. Token present: %s, Has verifier: %s, Retry: %s. "
                    "This usually indicates session expiration or mismatched tokens.",
                    bool(request_token),
                    bool(verifier),
                    request.GET.get("retry"),
                )
                return _usos_retry_or_error(request, redirect_url, jwt, error="invalid_token")

            try:
                access_token, access_token_secret = await client.authorize(
                    verifier, request_token, request_token_secret
                )
            except USOSAPIException as e:
                logger.error(
                    "USOS API authorization failed. Error: %s, Status: %s, Response: %s, Has verifier: %s, Retry: %s",
                    str(e),
                    getattr(e, "status", "N/A"),
                    getattr(e, "response", "N/A"),
                    bool(verifier),
                    request.GET.get("retry"),
                    exc_info=True,
                )
                return _usos_retry_or_error(request, redirect_url, jwt, error="authorization_failed")

            user, created = await update_user_data_from_usos(client, access_token, access_token_secret)

            if user.is_banned:
                logger.warning("Banned user attempted USOS login. Email: %s", user.email)
                return await ahandle_oauth_login_result(
                    request, user, jwt=jwt, redirect_url=redirect_url, guest_id=guest_id
                )

            if not user.is_student_and_not_staff:
                logger.warning(
                    "User rejected: not an active student. Email: %s, Created: %s",
                    user.email,
                    created,
                )
                messages.error(
                    request,
                    "Aby korzystać z Testownika, musisz być aktywnym studentem Politechniki Wrocławskiej.",
                )
                if created:
                    await user.adelete()
                if jwt:
                    return redirect(add_query_params(redirect_url, {"error": "not_student"}))
                return redirect("index")

        return await ahandle_oauth_login_result(request, user, jwt=jwt, redirect_url=redirect_url, guest_id=guest_id)


def _usos_retry_or_error(request, redirect_url: str, jwt: bool, *, error: str):
    """
    Handle a recoverable USOS failure: on first attempt, bounce back through /api/login/usos/
    with `retry=1`; if already retried, return the appropriate error response.
    """
    if request.GET.get("retry") != "1":
        login_url = request.build_absolute_uri("/api/login/usos/")
        params = request.GET.copy()
        params["retry"] = "1"
        return redirect(add_query_params(login_url, dict(params)))

    if jwt:
        return redirect(add_query_params(redirect_url, {"error": error}))
    return HttpResponseForbidden()


async def update_user_data_from_usos(client=None, access_token=None, access_token_secret=None):
    if client is None:
        if not access_token or not access_token_secret:
            logger.error("update_user_data_from_usos called without client or tokens")
            raise ValueError("Either client or access_token and access_token_secret must be provided")
        async with USOSClient(
            "https://apps.usos.pwr.edu.pl/",
            os.getenv("USOS_CONSUMER_KEY"),
            os.getenv("USOS_CONSUMER_SECRET"),
            trust_env=True,
        ) as owned_client:
            owned_client.load_access_token(access_token, access_token_secret)
            return await _sync_usos_user(owned_client, access_token, access_token_secret)

    return await _sync_usos_user(client, access_token, access_token_secret)


async def _sync_usos_user(client, access_token, access_token_secret):
    try:
        user_data = await client.user_service.get_user()
    except Exception as e:
        logger.error("Failed to get user data from USOS: %s", str(e), exc_info=True)
        raise

    defaults = {
        "first_name": user_data.first_name,
        "last_name": user_data.last_name,
        "email": user_data.email,
        "student_number": user_data.student_number,
        "sex": user_data.sex.value,
        "student_status": user_data.student_status.value,
        "staff_status": user_data.staff_status.value,
        "photo_url": user_data.photo_urls.get(
            "original",
            user_data.photo_urls.get("200x200", next(iter(user_data.photo_urls.values()), None)),
        ),
    }

    if user_data.staff_status.value >= StaffStatus.NON_ACADEMIC_STAFF.value:
        defaults["account_type"] = AccountType.LECTURER
    elif user_data.student_status.value >= StudentStatus.INACTIVE_STUDENT.value:
        defaults["account_type"] = AccountType.STUDENT

    if access_token and access_token_secret:
        defaults["access_token"] = access_token
        defaults["access_token_secret"] = access_token_secret

    user_obj, created = await User.objects.aupdate_or_create(usos_id=user_data.id, defaults=defaults)

    if created:
        user_obj.set_unusable_password()
        await user_obj.asave()

    user_groups = await client.group_service.get_groups_for_participant(
        fields=[
            "course_unit_id",
            "group_number",
            "course_name",
            "term_id",
            "class_type",
        ]
    )

    for group in user_groups:
        try:
            term = await Term.objects.aget(
                id=group.term_id,
            )
        except Term.DoesNotExist:
            term_response = await client.term_service.get_term(group.term_id)
            term = await Term.objects.acreate(
                id=term_response.id,
                name=term_response.name.pl,
                start_date=term_response.start_date,
                end_date=term_response.end_date,
                finish_date=term_response.finish_date,
            )
        group_obj, _ = await StudyGroup.objects.aupdate_or_create(
            id=f"{group.course_unit_id}-{group.group_number}",
            defaults={
                "name": f"{group.course_name.pl} - {group.class_type.pl}, grupa {group.group_number}",
                "term": term,
            },
        )
        await user_obj.study_groups.aadd(group_obj)

    return user_obj, created
