from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from oauth2_provider.models import AbstractApplication, AccessToken, RefreshToken, get_application_model
from rest_framework.test import APITestCase

from oauth_integrations.models import OAuthClientMetadata
from users.models import User


class AuthorizedAppsViewSetTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="authorized-apps-user@example.com",
            first_name="Authorized",
            last_name="Apps",
            password="testpassword123",
        )
        self.other_user = User.objects.create_user(
            email="authorized-apps-other@example.com",
            first_name="Other",
            last_name="User",
            password="testpassword123",
        )
        self.application = get_application_model().objects.create(
            name="MCP Client",
            client_id="mcp-client",
            client_type=AbstractApplication.CLIENT_PUBLIC,
            authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:3333/callback",
        )

    def _create_access_token(self, *, user, application, token, scope, created):
        access_token = AccessToken.objects.create(
            user=user,
            application=application,
            token=token,
            expires=timezone.now() + timedelta(hours=1),
            scope=scope,
        )
        AccessToken.objects.filter(pk=access_token.pk).update(created=created)
        access_token.refresh_from_db()
        return access_token

    def test_list_requires_authenticated_user(self):
        response = self.client.get(reverse("authorized_apps"))

        self.assertEqual(response.status_code, 401)

    def test_list_returns_latest_token_per_authorized_app(self):
        now = timezone.now()
        self._create_access_token(
            user=self.user,
            application=self.application,
            token="older-token",
            scope="quizzes:read",
            created=now - timedelta(minutes=1),
        )
        self._create_access_token(
            user=self.user,
            application=self.application,
            token="newer-token",
            scope="quizzes:write",
            created=now,
        )
        self._create_access_token(
            user=self.other_user,
            application=self.application,
            token="other-user-token",
            scope="user:read",
            created=now + timedelta(minutes=1),
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("authorized_apps"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["client_id"], "mcp-client")
        self.assertEqual(response.data[0]["oauth_application_id"], "mcp-client")
        self.assertEqual(response.data[0]["client_name"], "MCP Client")
        self.assertEqual(response.data[0]["scopes"], "quizzes:write")

    def test_destroy_revokes_access_and_refresh_tokens_for_current_user(self):
        access_token = self._create_access_token(
            user=self.user,
            application=self.application,
            token="token-to-revoke",
            scope="quizzes:read",
            created=timezone.now(),
        )
        RefreshToken.objects.create(
            user=self.user,
            application=self.application,
            access_token=access_token,
            token="refresh-to-revoke",
        )
        self._create_access_token(
            user=self.other_user,
            application=self.application,
            token="other-user-token",
            scope="quizzes:read",
            created=timezone.now(),
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.delete(reverse("authorized_app_detail", kwargs={"client_id": "mcp-client"}))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(AccessToken.objects.filter(user=self.user, application=self.application).exists())
        self.assertFalse(RefreshToken.objects.filter(user=self.user, application=self.application).exists())
        self.assertTrue(AccessToken.objects.filter(user=self.other_user, application=self.application).exists())

    def test_destroy_returns_not_found_when_user_has_no_tokens_for_app(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.delete(reverse("authorized_app_detail", kwargs={"client_id": "mcp-client"}))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"], "No tokens found for this app")

    def test_destroy_supports_cimd_client_id_url(self):
        client_id_url = "https://client.example/.well-known/oauth-client"
        OAuthClientMetadata.objects.create(
            application=self.application,
            client_id_url=client_id_url,
            client_name="CIMD Client",
            redirect_uris=["https://client.example/callback"],
            grant_types=["authorization_code"],
            response_types=["code"],
            fetched_at=timezone.now(),
        )
        self._create_access_token(
            user=self.user,
            application=self.application,
            token="cimd-token-to-revoke",
            scope="quizzes:read",
            created=timezone.now(),
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.delete(reverse("authorized_app_detail", kwargs={"client_id": client_id_url}))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(AccessToken.objects.filter(user=self.user, application=self.application).exists())
