from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from oauth2_provider.models import AbstractApplication, AccessToken, get_application_model
from rest_framework.test import APITestCase

from oauth_integrations.models import OAuthApplicationMetadata, OAuthClientMetadata
from users.models import User

AUTHORIZATION_PARAMS = {
    "response_type": "code",
    "redirect_uri": "http://localhost:3333/callback",
    "code_challenge": "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqr",
    "code_challenge_method": "S256",
    "scope": "quizzes:read user:read",
    "state": "test-state",
}


@override_settings(FRONTEND_URL="http://localhost:3000")
class OAuthAuthorizationAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="oauth-user@example.com",
            first_name="OAuth",
            last_name="User",
            password="testpassword123",
        )
        Application = get_application_model()
        self.application = Application.objects.create(
            name="MCP Client",
            client_id="test-client",
            client_type=AbstractApplication.CLIENT_PUBLIC,
            authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=AUTHORIZATION_PARAMS["redirect_uri"],
        )
        self.authorization_params = {
            **AUTHORIZATION_PARAMS,
            "client_id": self.application.client_id,
        }

    def test_authorization_request_requires_authenticated_jwt_user(self):
        response = self.client.get(reverse("oauth_authorize_request"), self.authorization_params)

        self.assertEqual(response.status_code, 401)

    def test_authorization_request_returns_consent_details(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(reverse("oauth_authorize_request"), self.authorization_params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["client_name"], "MCP Client")
        self.assertEqual(response.data["redirect_uri"], AUTHORIZATION_PARAMS["redirect_uri"])
        self.assertEqual(
            [scope["value"] for scope in response.data["scopes"]],
            ["quizzes:read", "user:read"],
        )

    def test_authorization_request_returns_application_logo_uri(self):
        OAuthApplicationMetadata.objects.create(
            application=self.application,
            logo_uri="https://example.com/logo.png",
        )
        self.client.force_authenticate(user=self.user)

        response = self.client.get(reverse("oauth_authorize_request"), self.authorization_params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["logo_uri"], "https://example.com/logo.png")

    def test_authorization_request_returns_native_cimd_display_metadata(self):
        client_id = "https://example.com/client.json"
        application = get_application_model().objects.create(
            name="Native MCP Client",
            client_id=client_id,
            client_type=AbstractApplication.CLIENT_PUBLIC,
            authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=AUTHORIZATION_PARAMS["redirect_uri"],
        )
        OAuthClientMetadata.objects.create(
            application=None,
            client_id_url=client_id,
            client_name=application.name,
            client_uri="https://example.com",
            logo_uri="https://example.com/logo.png",
            redirect_uris=[AUTHORIZATION_PARAMS["redirect_uri"]],
            fetched_at=timezone.now(),
        )
        authorization_params = {**self.authorization_params, "client_id": client_id}
        self.client.force_authenticate(user=self.user)

        response = self.client.get(reverse("oauth_authorize_request"), authorization_params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["client_uri"], "https://example.com")
        self.assertEqual(response.data["logo_uri"], "https://example.com/logo.png")

    @patch("oauth2_provider.cimd.SafeMetadataFetcher.fetch")
    def test_end_to_end_fresh_cimd_authorization_flow(self, mock_fetch):
        client_id = "https://example.com/fresh-e2e.json"
        mock_fetch.return_value = (
            {
                "client_id": client_id,
                "client_name": "Fresh E2E Client",
                "redirect_uris": [AUTHORIZATION_PARAMS["redirect_uri"]],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
            },
            3600,
        )
        authorization_params = {**self.authorization_params, "client_id": client_id}
        self.client.force_authenticate(user=self.user)

        response = self.client.get(reverse("oauth_authorize_request"), authorization_params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["client_name"], "Fresh E2E Client")
        self.assertTrue(
            OAuthClientMetadata.objects.filter(
                client_id_url=client_id,
                client_name="Fresh E2E Client",
            ).exists()
        )

        response = self.client.post(
            reverse("oauth_authorize_request"),
            {
                "authorization_params": authorization_params,
                "scopes": ["quizzes:read"],
                "allow": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("code=", response.data["redirect_url"])
        mock_fetch.assert_called_once_with(client_id)

    def test_authorization_request_approval_returns_redirect_url(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            reverse("oauth_authorize_request"),
            {
                "authorization_params": self.authorization_params,
                "scopes": ["quizzes:read"],
                "allow": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["redirect_url"].startswith(f"{AUTHORIZATION_PARAMS['redirect_uri']}?"))
        self.assertIn("code=", response.data["redirect_url"])
        self.assertIn("state=test-state", response.data["redirect_url"])

    def test_authorization_request_denial_returns_access_denied_redirect(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            reverse("oauth_authorize_request"),
            {
                "authorization_params": self.authorization_params,
                "scopes": [],
                "allow": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["redirect_url"].startswith(f"{AUTHORIZATION_PARAMS['redirect_uri']}?"))
        self.assertIn("error=access_denied", response.data["redirect_url"])
        self.assertIn("state=test-state", response.data["redirect_url"])

    def test_implicit_grant_is_rejected(self):
        implicit_application = get_application_model().objects.create(
            name="Implicit Client",
            client_id="implicit-client",
            client_type=AbstractApplication.CLIENT_PUBLIC,
            authorization_grant_type=AbstractApplication.GRANT_IMPLICIT,
            redirect_uris=AUTHORIZATION_PARAMS["redirect_uri"],
        )
        authorization_params = {
            **self.authorization_params,
            "client_id": implicit_application.client_id,
            "response_type": "token",
        }
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            reverse("oauth_authorize_request"),
            {
                "authorization_params": authorization_params,
                "scopes": ["quizzes:read", "user:read"],
                "allow": True,
            },
            format="json",
        )

        self.assertIn("redirect_url", response.data)
        self.assertIn("error=", response.data["redirect_url"])
        self.assertNotIn("access_token=", response.data["redirect_url"])
        self.assertFalse(AccessToken.objects.filter(application=implicit_application).exists())
