import urllib.parse
from unittest.mock import AsyncMock, MagicMock, patch

from django.http import HttpResponseRedirect
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from users.models import User
from users.views.oauth import _decode_usos_redirect, _encode_usos_redirect


@override_settings(DEBUG=True)
class SolvroOAuthTests(APITestCase):
    @patch("users.views.oauth.oauth.create_client")
    def test_solvro_login_redirect_url(self, mock_create_client):
        """Test SolvroLoginView builds the correct callback URL with query parameters."""
        mock_auth_client = MagicMock()
        mock_create_client.return_value = mock_auth_client

        mock_auth_client.authorize_redirect.return_value = HttpResponseRedirect("http://auth.solvro.pl/login")

        redirect_param = "http://localhost:3000/quizzes?foo=bar"
        guest_id = "test-guest-id"

        url = reverse("login")
        self.client.get(
            url,
            {"jwt": "true", "redirect": redirect_param, "guest_id": guest_id},
        )

        mock_create_client.assert_called_with("solvro-auth")

        self.assertTrue(mock_auth_client.authorize_redirect.called)

        args, kwargs = mock_auth_client.authorize_redirect.call_args

        callback_url = args[1]
        self.assertIn("/api/authorize/", callback_url)
        self.assertIn("jwt=true", callback_url)

        expected_encoded_redirect = urllib.parse.quote_plus(redirect_param)
        self.assertIn(f"redirect={expected_encoded_redirect}", callback_url)
        self.assertIn(f"guest_id={guest_id}", callback_url)

    @patch("users.views.oauth.oauth.create_client")
    def test_solvro_authorize_success(self, mock_create_client):
        """Test SolvroAuthorizeView successful login logic via mock."""
        mock_auth_client = MagicMock()
        mock_create_client.return_value = mock_auth_client

        mock_auth_client.authorize_access_token.return_value = {"access_token": "mock_token"}

        mock_response = MagicMock()
        mock_response.json.return_value = {"email": "testuser@solvro.pl"}
        mock_auth_client.get.return_value = mock_response

        url = reverse("authorize")
        response = self.client.get(url, {"jwt": "true", "redirect": "http://localhost:3000/"})

        self.assertTrue(User.objects.filter(email="testuser@solvro.pl").exists())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "http://localhost:3000/")

        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)


MOBILE_REDIRECT = (
    "http://localhost:3000/oauth/authorize?client_id=testownik-mobile"
    "&redirect_uri=testownik%3A%2F%2Fauth&scope=quizzes%3Aread+quizzes%3Awrite"
)


def _usos_client_mock():
    client = MagicMock()
    client.get_authorization_url = AsyncMock(return_value="https://apps.usos.pwr.edu.pl/authorize")
    client.connection.auth_manager.get_request_token.return_value = ("token", "secret")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return client, context


@override_settings(DEBUG=True)
@patch.dict("os.environ", {"USOS_CONSUMER_KEY": "key", "USOS_CONSUMER_SECRET": "secret"})
class UsosOAuthTests(APITestCase):
    @patch("users.views.oauth.USOSClient")
    def test_login_callback_has_no_percent_escapes(self, mock_usos_client):
        """USOS rejects the request-token signature for callbacks containing %-escapes."""
        client, mock_usos_client.return_value = _usos_client_mock()

        response = self.client.get(reverse("login_usos"), {"jwt": "true", "redirect": MOBILE_REDIRECT})

        self.assertEqual(response.status_code, 302)
        callback_url = client.get_authorization_url.call_args.args[0]
        self.assertNotIn("%", callback_url)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(callback_url).query)
        self.assertEqual(query["jwt"], ["true"])
        self.assertEqual(_decode_usos_redirect(query["redirect_b64"][0]), MOBILE_REDIRECT)

    @patch("users.views.oauth.USOSClient")
    def test_authorize_retry_restores_encoded_redirect(self, mock_usos_client):
        _, mock_usos_client.return_value = _usos_client_mock()

        response = self.client.get(
            reverse("authorize_usos"),
            {"jwt": "true", "redirect_b64": _encode_usos_redirect(MOBILE_REDIRECT), "oauth_token": "missing"},
        )

        self.assertEqual(response.status_code, 302)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(response.url).query)
        self.assertEqual(query["redirect"], [MOBILE_REDIRECT])
        self.assertEqual(query["retry"], ["1"])
        self.assertNotIn("redirect_b64", query)

    @patch("users.views.oauth.USOSClient")
    def test_authorize_rejects_unsafe_encoded_redirect(self, mock_usos_client):
        _, mock_usos_client.return_value = _usos_client_mock()

        response = self.client.get(
            reverse("authorize_usos"),
            {
                "jwt": "true",
                "redirect_b64": _encode_usos_redirect("https://evil.example/"),
                "oauth_token": "missing",
                "retry": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(response.url.startswith("https://evil.example"))
