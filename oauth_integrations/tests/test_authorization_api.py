from django.test import override_settings
from django.urls import reverse
from oauth2_provider.models import AbstractApplication, get_application_model
from rest_framework.test import APITestCase

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
