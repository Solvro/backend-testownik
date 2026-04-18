import logging
import os
from asyncio import CancelledError, sleep

import dotenv
from adrf.views import APIView as AsyncAPIView
from asgiref.sync import sync_to_async
from django.contrib import messages
from django.contrib.auth import alogin as async_auth_login
from django.contrib.auth import login as auth_login
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, resolve_url
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from usos_api import USOSAPIException, USOSClient
from usos_api.models import StaffStatus, StudentStatus

from testownik_core.settings import oauth
from users.auth_cookies import set_jwt_cookies
from users.models import AccountType, StudyGroup, Term, User
from users.serializers import UserTokenObtainPairSerializer
from users.services import migrate_guest_to_user

from .utils import (
    add_query_params,
    build_oauth_callback_url,
    get_safe_redirect_url,
    remove_query_params,
)

dotenv.load_dotenv()

logger = logging.getLogger(__name__)


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
        parameters=[
            OpenApiParameter(
                "jwt",
                OpenApiTypes.BOOL,
                OpenApiParameter.QUERY,
                description=(
                    "If true, the authorize callback returns JWT tokens via cookies instead of creating a session."
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
        ],
        responses={
            302: OpenApiResponse(description="Redirect to Solvro OAuth provider."),
            400: OpenApiResponse(description="Invalid redirect URL."),
        },
        tags=["Authentication"],
    )
    def get(self, request):
        confirm_user = request.GET.get("confirm_user", "false") == "true"
        jwt = request.GET.get("jwt", "false") == "true"
        raw_redirect_url = request.GET.get("redirect", "")
        redirect_url = get_safe_redirect_url(raw_redirect_url, request, default="")
        guest_id = request.GET.get("guest_id", "")

        if raw_redirect_url and not redirect_url:
            return HttpResponseBadRequest("Invalid redirect URL")

        callback_params = {"jwt": str(jwt).lower()}
        if redirect_url:
            callback_params["redirect"] = redirect_url
        if guest_id:
            callback_params["guest_id"] = guest_id

        callback_url = add_query_params(request.build_absolute_uri("/api/authorize/"), callback_params)

        additional_params = {}
        if confirm_user:
            additional_params["prompt"] = "login"
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
        parameters=[
            OpenApiParameter(
                "jwt",
                OpenApiTypes.BOOL,
                OpenApiParameter.QUERY,
                description=(
                    "If true, the authorize callback returns JWT tokens"
                    " via cookies instead of creating a session."
                    " Requires `redirect` to be set."
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
                description="If true, forces USOS to re-prompt the user for credentials.",
                default=False,
            ),
            OpenApiParameter(
                "guest_id",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Guest account ID to migrate to the authenticated user.",
            ),
        ],
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
        confirm_user = request.GET.get("confirm_user", "false") == "true"
        jwt = request.GET.get("jwt", "false") == "true"
        raw_redirect_url = request.GET.get("redirect", "")
        redirect_url = get_safe_redirect_url(raw_redirect_url, request, default="")
        guest_id = request.GET.get("guest_id", "")

        if raw_redirect_url and not redirect_url:
            return HttpResponseBadRequest("Invalid redirect URL")

        if jwt and not redirect_url:
            return HttpResponseForbidden("Redirect URL must be provided when using JWT")

        callback_params = {"jwt": str(jwt).lower()}
        if redirect_url:
            callback_params["redirect"] = redirect_url
        if guest_id:
            callback_params["guest_id"] = guest_id

        callback_url = build_oauth_callback_url(request, "/api/authorize/usos/", callback_params)

        max_retries = 3
        retry_delay = 2

        usos_key = os.getenv("USOS_CONSUMER_KEY")
        usos_secret = os.getenv("USOS_CONSUMER_SECRET")

        if not usos_key or not usos_secret:
            logger.error(
                "USOS credentials not configured. USOS_CONSUMER_KEY=%s, USOS_CONSUMER_SECRET=%s",
                "<set>" if usos_key else "<missing>",
                "<set>" if usos_secret else "<missing>",
            )
            return redirect(add_query_params(redirect_url or "index", {"error": "usos_unavailable"}))

        for attempt in range(max_retries):
            try:
                async with USOSClient(
                    "https://apps.usos.pwr.edu.pl/",
                    usos_key,
                    usos_secret,
                    trust_env=True,
                ) as client:
                    client.set_scopes(["offline_access", "studies", "email", "photo", "grades"])
                    authorization_url = await client.get_authorization_url(callback_url, confirm_user)
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
                    jwt,
                    redirect_url,
                    exc_info=True,
                )

                if attempt < max_retries - 1:
                    await sleep(retry_delay)
                    continue

                return redirect(add_query_params(redirect_url or "index", {"error": "usos_unavailable"}))

        return redirect(add_query_params(redirect_url or "index", {"error": "usos_unavailable"}))


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
        parameters=[
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
        ],
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

        redirect_url = get_safe_redirect_url(
            request.GET.get("redirect", resolve_url("index")), request, default=resolve_url("index")
        )

        if not profile.get("email"):
            logger.error("Solvro user profile missing email. Profile keys: %s", list(profile.keys()))
            if request.GET.get("jwt", "false") == "true":
                return redirect(add_query_params(redirect_url, {"error": "no_email"}))
            messages.error(request, "Brak adresu email w profilu użytkownika.")
            return redirect(redirect_url)

        user, created = User.objects.update_or_create(
            email=profile["email"],
            defaults={
                "photo_url": f"https://api.dicebear.com/9.x/adventurer/svg?seed={profile['email']}",
            },
            create_defaults={
                "account_type": AccountType.EMAIL,
                "photo_url": f"https://api.dicebear.com/9.x/adventurer/svg?seed={profile['email']}",
            },
        )

        if user.is_banned:
            logger.warning("Banned user attempted login. Email: %s", user.email)
            if request.GET.get("jwt", "false") == "true":
                auth_params = {"error": "user_banned"}
                if user.ban_reason:
                    auth_params["ban_reason"] = user.ban_reason
                return redirect(add_query_params(redirect_url, auth_params))

            messages.error(request, f"Twoje konto zostało zablokowane: {user.ban_reason or 'Brak powodu'}")
            return redirect(redirect_url)

        guest_id = request.GET.get("guest_id", "")
        if guest_id:
            migrate_guest_to_user(guest_id, user)

        if request.GET.get("jwt", "false") == "true":
            refresh = UserTokenObtainPairSerializer.get_token(user)
            response = redirect(remove_query_params(redirect_url, ["error"]))
            set_jwt_cookies(response, str(refresh.access_token), str(refresh))
            return response

        auth_login(request, user)
        return redirect(redirect_url)


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
        redirect_url = get_safe_redirect_url(
            request.GET.get("redirect", resolve_url("index")), request, default=resolve_url("index")
        )

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
                if request.GET.get("retry") != "1":
                    login_url = request.build_absolute_uri("/api/login/usos/")
                    params = request.GET.copy()
                    params["retry"] = "1"
                    return redirect(add_query_params(login_url, dict(params)))

                if request.GET.get("jwt", "false") == "true":
                    return redirect(add_query_params(redirect_url, {"error": "invalid_token"}))
                return HttpResponseForbidden()

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
                if request.GET.get("retry") != "1":
                    login_url = request.build_absolute_uri("/api/login/usos/")
                    params = request.GET.copy()
                    params["retry"] = "1"
                    return redirect(add_query_params(login_url, dict(params)))

                if request.GET.get("jwt", "false") == "true":
                    return redirect(add_query_params(redirect_url, {"error": "authorization_failed"}))
                return HttpResponseForbidden()

            user, created = await update_user_data_from_usos(client, access_token, access_token_secret)

            if user.is_banned:
                logger.warning("Banned user attempted USOS login. Email: %s", user.email)
                if request.GET.get("jwt", "false") == "true":
                    auth_params = {"error": "user_banned"}
                    if user.ban_reason:
                        auth_params["ban_reason"] = user.ban_reason
                    return redirect(add_query_params(redirect_url, auth_params))

                messages.error(request, f"Twoje konto zostało zablokowane: {user.ban_reason or 'Brak powodu'}")
                return redirect(redirect_url)

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
                if request.GET.get("jwt", "false") == "true":
                    return redirect(add_query_params(redirect_url, {"error": "not_student"}))
                return redirect("index")

        guest_id = request.GET.get("guest_id", "")
        if guest_id:
            await sync_to_async(migrate_guest_to_user)(guest_id, user)

        if request.GET.get("jwt", "false") == "true":
            refresh = await sync_to_async(UserTokenObtainPairSerializer.get_token)(user)
            response = redirect(remove_query_params(redirect_url, ["error"]))
            set_jwt_cookies(response, str(refresh.access_token), str(refresh))
            return response

        await async_auth_login(request, user)
        return redirect(redirect_url)


async def update_user_data_from_usos(client=None, access_token=None, access_token_secret=None):
    if not client:
        if not access_token or not access_token_secret:
            logger.error("update_user_data_from_usos called without client or tokens")
            raise ValueError("Either client or access_token and access_token_secret must be provided")
        async with USOSClient(
            "https://apps.usos.pwr.edu.pl/",
            os.getenv("USOS_CONSUMER_KEY"),
            os.getenv("USOS_CONSUMER_SECRET"),
            trust_env=True,
        ) as client:
            client.load_access_token(access_token, access_token_secret)
            try:
                user_data = await client.user_service.get_user()
            except Exception as e:
                logger.error("Failed to get user data from USOS: %s", str(e), exc_info=True)
                raise
    else:
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