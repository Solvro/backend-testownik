import logging

from django.conf import settings
from django.http import Http404, QueryDict
from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.models import (
    AccessToken,
    RefreshToken,
    get_application_model,
)
from oauth2_provider.scopes import get_scopes_backend
from oauth2_provider.views.mixins import OAuthLibMixin
from rest_framework import mixins, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from oauth_integrations.models import OAuthClientMetadata
from oauth_integrations.oauth_cimd import (
    CIMDError,
    get_cimd_metadata_for_application,
    get_or_create_cimd_application,
    is_cimd_client_id,
    resolve_application_from_public_client_id,
)
from oauth_integrations.serializers import AuthorizationDecisionSerializer, AuthorizedAppSerializer

logger = logging.getLogger(__name__)


def _oauth_error_redirect_url(oauth_error):
    redirect_uri = oauth_error.redirect_uri or ""
    separator = "&" if "?" in redirect_uri else "?"
    return redirect_uri + separator + oauth_error.urlencoded


def _friendly_oauth_error_message(error):
    oauth_error = error.oauthlib_error
    error_code = getattr(oauth_error, "error", "") or "invalid_request"
    description = getattr(oauth_error, "description", "") or ""

    if "client_id" in description:
        return "The app could not be verified. Check that its client metadata document URL is correct."
    if "redirect_uri" in description:
        return "The redirect URI is not allowed for this app. Check the app's client metadata document."
    if "code_challenge" in description or "PKCE" in description:
        return "The app did not send a valid PKCE challenge. Ask the app to retry the connection."
    if error_code == "unsupported_response_type":
        return "This authorization request uses an unsupported response type."
    if error_code == "invalid_scope":
        return "The app requested an invalid or unsupported scope."
    return "The authorization request is invalid. Ask the app to start the connection again."


def _log_oauth_toolkit_error(message, error, *, client_id="", redirect_uri=""):
    oauth_error = error.oauthlib_error
    error_code = getattr(oauth_error, "error", "") or "unknown"
    if error_code == "access_denied":
        message = "OAuth authorization denied by user"
        log = logger.info
    else:
        log = logger.warning
    log(
        "%s: error=%s description=%s client_id=%s redirect_uri=%s",
        message,
        error_code,
        getattr(oauth_error, "description", "") or "",
        client_id,
        redirect_uri,
    )


def _preflight_client_id(client_id):
    if not client_id:
        return "The authorization request is missing a client_id."

    application = get_application_model().objects.filter(client_id=client_id).first()
    if application is not None:
        return ""

    if is_cimd_client_id(client_id) or "://" in client_id:
        try:
            get_or_create_cimd_application(client_id)
        except CIMDError as exc:
            logger.warning("CIMD client preflight failed: client_id=%s error=%s", client_id, exc)
            return "Unable to validate client metadata for the provided client_id."
        return ""

    return "The client_id is not registered and is not a valid client metadata document URL."


class AuthorizationRequestAPIView(OAuthLibMixin, APIView):
    """JSON OAuth consent API consumed by the frontend authorize page."""

    permission_classes = [IsAuthenticated]

    def _get_application(self, client_id):
        return resolve_application_from_public_client_id(client_id)

    def _request_with_authorization_params(self, request, params):
        raw_request = request._request
        original_get = raw_request.GET
        original_query_string = raw_request.META.get("QUERY_STRING", "")
        original_user = raw_request.user

        query = QueryDict("", mutable=True)
        for key, value in params.items():
            if isinstance(value, list):
                query.setlist(key, [str(item) for item in value])
            elif value is not None:
                query[key] = str(value)
        query_string = query.urlencode()
        raw_request.GET = query
        raw_request.META["QUERY_STRING"] = query_string
        raw_request.user = request.user
        return raw_request, original_get, original_query_string, original_user

    def _restore_request(self, raw_request, original_get, original_query_string, original_user):
        raw_request.GET = original_get
        raw_request.META["QUERY_STRING"] = original_query_string
        raw_request.user = original_user

    def _validate_params(self, request, params):
        client_id = params.get("client_id", "")
        preflight_error = _preflight_client_id(client_id)
        if preflight_error:
            return None, None, Response({"error": preflight_error}, status=400)

        raw_request, original_get, original_query_string, original_user = self._request_with_authorization_params(
            request, params
        )
        try:
            scopes, credentials = self.validate_authorization_request(raw_request)
        except OAuthToolkitError as error:
            _log_oauth_toolkit_error(
                "OAuth authorization request validation failed",
                error,
                client_id=client_id,
                redirect_uri=params.get("redirect_uri", ""),
            )
            oauth_error = error.oauthlib_error
            if getattr(oauth_error, "redirect_uri", None):
                return None, None, Response({"redirect_url": _oauth_error_redirect_url(oauth_error)})
            return None, None, Response({"error": _friendly_oauth_error_message(error)}, status=400)
        except Exception:
            logger.exception("Unexpected OAuth authorization request validation failure: client_id=%s", client_id)
            raise
        finally:
            self._restore_request(raw_request, original_get, original_query_string, original_user)

        return scopes, credentials, None

    def get(self, request):
        scopes, credentials, error_response = self._validate_params(request, request.query_params)
        if error_response is not None:
            return error_response

        application = self._get_application(credentials["client_id"])
        if application is None:
            return Response({"error": "Invalid OAuth client."}, status=400)

        all_scopes = get_scopes_backend().get_all_scopes()
        metadata = get_cimd_metadata_for_application(application)
        return Response(
            {
                "client_id": metadata.client_id_url if metadata else application.client_id,
                "client_name": metadata.client_name if metadata else application.name,
                "client_uri": metadata.client_uri if metadata else "",
                "logo_uri": metadata.logo_uri if metadata else "",
                "redirect_uri": credentials["redirect_uri"],
                "scopes": [{"value": scope, "description": all_scopes[scope]} for scope in scopes],
            }
        )

    def post(self, request):
        serializer = AuthorizationDecisionSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("Invalid OAuth authorization decision payload: errors=%s", serializer.errors)
            return Response({"error": serializer.errors}, status=400)

        authorization_params = serializer.validated_data["authorization_params"]
        scopes, credentials, error_response = self._validate_params(request, authorization_params)
        if error_response is not None:
            return error_response

        requested_scopes = set(scopes)
        approved_scopes = serializer.validated_data["scopes"]
        if not set(approved_scopes).issubset(requested_scopes):
            logger.warning(
                "OAuth authorization decision included unrequested scopes: client_id=%s approved=%s requested=%s",
                authorization_params.get("client_id", ""),
                approved_scopes,
                scopes,
            )
            return Response({"error": "Approved scopes must be a subset of the requested scopes."}, status=400)

        allow = serializer.validated_data["allow"]
        scope_string = " ".join(approved_scopes)

        raw_request, original_get, original_query_string, original_user = self._request_with_authorization_params(
            request, authorization_params
        )
        try:
            redirect_url, _headers, _body, _status = self.create_authorization_response(
                request=raw_request,
                scopes=scope_string,
                credentials=credentials,
                allow=allow,
            )
        except OAuthToolkitError as error:
            _log_oauth_toolkit_error(
                "OAuth authorization response creation failed",
                error,
                client_id=authorization_params.get("client_id", ""),
                redirect_uri=credentials.get("redirect_uri", ""),
            )
            oauth_error = error.oauthlib_error
            if getattr(oauth_error, "redirect_uri", None):
                return Response({"redirect_url": _oauth_error_redirect_url(oauth_error)})
            return Response({"error": _friendly_oauth_error_message(error)}, status=400)
        except Exception:
            logger.exception(
                "Unexpected OAuth authorization response creation failure: client_id=%s",
                authorization_params.get("client_id", ""),
            )
            raise
        finally:
            self._restore_request(raw_request, original_get, original_query_string, original_user)

        return Response({"redirect_url": redirect_url})


class AuthorizationServerMetadataView(APIView):
    """RFC 8414 — OAuth 2.0 Authorization Server Metadata."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        issuer = settings.SITE_URL
        return Response(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{settings.FRONTEND_URL}/oauth/authorize",
                "token_endpoint": f"{issuer}/api/oauth/token/",
                "revocation_endpoint": f"{issuer}/api/oauth/revoke_token/",
                "introspection_endpoint": f"{issuer}/api/oauth/introspect/",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "client_id_metadata_document_supported": True,
                "scopes_supported": list(settings.OAUTH2_PROVIDER["SCOPES"].keys()),
                "token_endpoint_auth_methods_supported": [
                    "none",
                    "client_secret_basic",
                    "client_secret_post",
                ],
            }
        )


class ProtectedResourceMetadataView(APIView):
    """RFC 9728 — OAuth 2.0 Protected Resource Metadata."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        site_url = settings.SITE_URL
        mcp_endpoint = settings.DJANGO_MCP_ENDPOINT.strip("/")
        return Response(
            {
                "resource": f"{site_url}/{mcp_endpoint}",
                "authorization_servers": [site_url],
                "scopes_supported": list(settings.OAUTH2_PROVIDER["SCOPES"].keys()),
            }
        )


class AuthorizedAppsViewSet(mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Manage OAuth apps authorized by the current user."""

    permission_classes = [IsAuthenticated]
    serializer_class = AuthorizedAppSerializer
    lookup_url_kwarg = "client_id"

    def get_queryset(self):
        tokens = AccessToken.objects.filter(user=self.request.user).select_related("application").order_by("-created")
        seen = set()
        apps = []
        for token in tokens:
            app = token.application
            if app is None or app.client_id in seen:
                continue
            seen.add(app.client_id)
            metadata = get_cimd_metadata_for_application(app)
            apps.append(
                {
                    "client_id": metadata.client_id_url if metadata else app.client_id,
                    "oauth_application_id": app.client_id,
                    "client_name": metadata.client_name if metadata else app.name,
                    "client_uri": metadata.client_uri if metadata else "",
                    "logo_uri": metadata.logo_uri if metadata else "",
                    "created": token.created,
                    "scopes": token.scope,
                }
            )
        return apps

    def destroy(self, request, *args, **kwargs):
        client_id = kwargs.get(self.lookup_url_kwarg)
        if not client_id:
            return Response({"error": "client_id is required"}, status=400)
        try:
            return super().destroy(request, *args, **kwargs)
        except Http404:
            return Response({"error": "No tokens found for this app"}, status=404)

    def get_object(self):
        client_id = self.kwargs.get(self.lookup_url_kwarg)
        application = self._get_application_for_revoke(client_id)
        if application is None or not self._has_user_tokens(application):
            raise Http404
        self.check_object_permissions(self.request, application)
        return application

    def perform_destroy(self, application):
        refresh_deleted, _ = RefreshToken.objects.filter(
            user=self.request.user,
            application=application,
        ).delete()
        access_deleted, _ = AccessToken.objects.filter(
            user=self.request.user,
            application=application,
        ).delete()
        if refresh_deleted == 0 and access_deleted == 0:
            raise Http404

    def _get_application_for_revoke(self, client_id):
        if is_cimd_client_id(client_id):
            metadata = OAuthClientMetadata.objects.select_related("application").filter(client_id_url=client_id).first()
            return metadata.application if metadata else None
        return get_application_model().objects.filter(client_id=client_id).first()

    def _has_user_tokens(self, application):
        return (
            AccessToken.objects.filter(user=self.request.user, application=application).exists()
            or RefreshToken.objects.filter(user=self.request.user, application=application).exists()
        )
