import urllib.parse
from unittest.mock import MagicMock, patch

from django.http import HttpResponseRedirect
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from users.models import User


class SolvroOAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("users.views.oauth.create_client")
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

    @patch("users.views.oauth.create_client")
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
