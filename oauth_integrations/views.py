import json

from django.conf import settings
from django.http import HttpResponseBadRequest
from django.utils import timezone
from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.models import (
    AccessToken,
    RefreshToken,
    get_access_token_model,
    get_application_model,
)
from oauth2_provider.scopes import get_scopes_backend
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.views import AuthorizationView
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


class ScopedAuthorizationView(AuthorizationView):
    """Consent screen that lets the user approve a subset of requested scopes.

    The default django-oauth-toolkit view renders the requested scopes as static
    text and grants all of them. We expose each scope as an individual checkbox;
    the template collects the checked scopes into the form's ``scope`` field, so
    the issued token only carries the scopes the user actually approved.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if context.get("authorization_error"):
            context["client_display_name"] = context.get("client_display_name", "This app")
            context["client_logo_uri"] = ""
            context["client_uri"] = ""
            context["scopes_zip"] = []
            context["form"] = None
            return context

        scopes = context.get("scopes", []) or []
        descriptions = context.get("scopes_descriptions", []) or []
        context["scopes_zip"] = list(zip(scopes, descriptions))
        application = context.get("application")
        metadata = get_cimd_metadata_for_application(application)
        context["is_cimd_client"] = metadata is not None
        context["client_display_name"] = metadata.client_name if metadata else application.name
        context["client_logo_uri"] = metadata.logo_uri if metadata else ""
        context["client_uri"] = metadata.client_uri if metadata else ""
        return context

    def _get_application(self, client_id):
        return resolve_application_from_public_client_id(client_id)

    def _preflight_client_id(self, client_id):
        if not client_id:
            return "The authorization request is missing a client_id."

        application = get_application_model().objects.filter(client_id=client_id).first()
        if application is not None:
            return ""

        if is_cimd_client_id(client_id) or "://" in client_id:
            try:
                get_or_create_cimd_application(client_id)
            except CIMDError as exc:
                return str(exc)
            return ""

        return "The client_id is not registered and is not a valid client metadata document URL."

    def _render_authorization_error(self, message, *, status=400, redirect_uri="", client_id=""):
        return self.render_to_response(
            self.get_context_data(
                authorization_error=True,
                error_title="Authorization request failed",
                error_message=message,
                client_id=client_id,
                redirect_uri=redirect_uri,
            ),
            status=status,
        )

    def _friendly_oauth_error_message(self, error):
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

    def error_response(self, error, application, **kwargs):
        oauth_error = error.oauthlib_error
        if getattr(oauth_error, "redirect_uri", None):
            return super().error_response(error, application, **kwargs)

        return self._render_authorization_error(
            self._friendly_oauth_error_message(error),
            status=getattr(oauth_error, "status_code", 400),
            redirect_uri=getattr(oauth_error, "redirect_uri", "") or "",
        )

    def get(self, request, *args, **kwargs):
        client_id = request.GET.get("client_id", "")
        preflight_error = self._preflight_client_id(client_id)
        if preflight_error:
            return self._render_authorization_error(
                preflight_error,
                client_id=client_id,
                redirect_uri=request.GET.get("redirect_uri", ""),
            )

        try:
            scopes, credentials = self.validate_authorization_request(request)
        except OAuthToolkitError as error:
            return self.error_response(error, application=None)

        prompt = request.GET.get("prompt")
        if prompt == "login":
            return self.handle_prompt_login()

        all_scopes = get_scopes_backend().get_all_scopes()
        kwargs["scopes_descriptions"] = [all_scopes[scope] for scope in scopes]
        kwargs["scopes"] = scopes

        application = self._get_application(credentials["client_id"])
        if application is None:
            return HttpResponseBadRequest("Invalid OAuth client.")

        kwargs["application"] = application
        kwargs["client_id"] = credentials["client_id"]
        kwargs["redirect_uri"] = credentials["redirect_uri"]
        kwargs["response_type"] = credentials["response_type"]
        kwargs["state"] = credentials["state"]
        if "code_challenge" in credentials:
            kwargs["code_challenge"] = credentials["code_challenge"]
        if "code_challenge_method" in credentials:
            kwargs["code_challenge_method"] = credentials["code_challenge_method"]
        if "nonce" in credentials:
            kwargs["nonce"] = credentials["nonce"]
        if "claims" in credentials:
            kwargs["claims"] = json.dumps(credentials["claims"])

        self.oauth2_data = kwargs
        form = self.get_form(self.get_form_class())
        kwargs["form"] = form

        require_approval = request.GET.get("approval_prompt", oauth2_settings.REQUEST_APPROVAL_PROMPT)

        if "ui_locales" in credentials and isinstance(credentials["ui_locales"], list):
            credentials["ui_locales"] = " ".join(credentials["ui_locales"])

        try:
            if application.skip_authorization:
                uri, _headers, _body, _status = self.create_authorization_response(
                    request=self.request, scopes=" ".join(scopes), credentials=credentials, allow=True
                )
                return self.redirect(uri, application)

            if require_approval == "auto":
                tokens = (
                    get_access_token_model()
                    .objects.filter(user=request.user, application=application, expires__gt=timezone.now())
                    .all()
                )

                for token in tokens:
                    if token.allow_scopes(scopes):
                        uri, _headers, _body, _status = self.create_authorization_response(
                            request=self.request,
                            scopes=" ".join(scopes),
                            credentials=credentials,
                            allow=True,
                        )
                        return self.redirect(uri, application)

        except OAuthToolkitError as error:
            return self.error_response(error, application)

        return self.render_to_response(self.get_context_data(**kwargs))

    def form_valid(self, form):
        client_id = form.cleaned_data["client_id"]
        application = self._get_application(client_id)
        if application is None:
            return HttpResponseBadRequest("Invalid OAuth client.")

        credentials = {
            "client_id": client_id,
            "redirect_uri": form.cleaned_data.get("redirect_uri"),
            "response_type": form.cleaned_data.get("response_type", None),
            "state": form.cleaned_data.get("state", None),
        }
        if form.cleaned_data.get("code_challenge", False):
            credentials["code_challenge"] = form.cleaned_data.get("code_challenge")
        if form.cleaned_data.get("code_challenge_method", False):
            credentials["code_challenge_method"] = form.cleaned_data.get("code_challenge_method")
        if form.cleaned_data.get("nonce", False):
            credentials["nonce"] = form.cleaned_data.get("nonce")
        if form.cleaned_data.get("claims", False):
            credentials["claims"] = form.cleaned_data.get("claims")

        scopes = form.cleaned_data.get("scope")
        allow = form.cleaned_data.get("allow")

        try:
            uri, _headers, _body, _status = self.create_authorization_response(
                request=self.request, scopes=scopes, credentials=credentials, allow=allow
            )
        except OAuthToolkitError as error:
            return self.error_response(error, application)

        self.success_url = uri
        return self.redirect(self.success_url, application)


class AuthorizationServerMetadataView(APIView):
    """RFC 8414 — OAuth 2.0 Authorization Server Metadata."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        issuer = settings.SITE_URL
        return Response(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/api/oauth/authorize/",
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


class AuthorizedAppsView(APIView):
    """Manage OAuth apps authorized by the current user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tokens = AccessToken.objects.filter(user=request.user).select_related("application").order_by("-created")
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
        return Response(apps)

    def delete(self, request, client_id=None):
        if not client_id:
            return Response({"error": "client_id is required"}, status=400)
        application = self._get_application_for_revoke(client_id)
        if application is None:
            return Response({"error": "No tokens found for this app"}, status=404)
        refresh_deleted, _ = RefreshToken.objects.filter(
            user=request.user,
            application=application,
        ).delete()
        access_deleted, _ = AccessToken.objects.filter(
            user=request.user,
            application=application,
        ).delete()
        if refresh_deleted == 0 and access_deleted == 0:
            return Response({"error": "No tokens found for this app"}, status=404)
        return Response(status=204)

    def _get_application_for_revoke(self, client_id):
        if is_cimd_client_id(client_id):
            metadata = OAuthClientMetadata.objects.select_related("application").filter(client_id_url=client_id).first()
            return metadata.application if metadata else None
        return get_application_model().objects.filter(client_id=client_id).first()
