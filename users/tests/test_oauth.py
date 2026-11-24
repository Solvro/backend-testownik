import urllib.parse
from unittest.mock import AsyncMock, MagicMock, patch

from django.http import HttpResponseRedirect
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase
from usos_api.models import StaffStatus, StudentStatus

from legal.models import LegalAcceptance, LegalDocumentKind, LegalDocumentVersion
from users.models import User


def publish_terms():
    terms = LegalDocumentVersion.objects.create(kind=LegalDocumentKind.TERMS, content="Regulamin")
    terms.publish()
    return terms


@override_settings(DEBUG=True)
# Pin redirect origins so a local FRONTEND_URL (e.g. :3001) doesn't reject the test redirect.
@patch("users.views.utils.ALLOWED_REDIRECT_ORIGINS", ["http://localhost:3000"])
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

        user = User.objects.get(email="testuser@solvro.pl")
        self.assertEqual(user.photo_url, f"https://api.dicebear.com/9.x/adventurer/png?seed={user.id}")
        self.assertNotIn("solvro.pl", user.photo_url.split("?", 1)[1])

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "http://localhost:3000/")

        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

    def _solvro_login(self, mock_create_client, email):
        mock_auth_client = mock_create_client.return_value
        mock_auth_client.authorize_access_token.return_value = {"access_token": "mock_token"}
        mock_auth_client.get.return_value.json.return_value = {"email": email}
        self.client.get(reverse("authorize"), {"jwt": "true", "redirect": "http://localhost:3000/"})

    @patch("users.views.oauth.oauth.create_client")
    def test_new_account_records_the_terms_in_force(self, mock_create_client):
        terms = publish_terms()

        self._solvro_login(mock_create_client, "new@solvro.pl")

        self.assertEqual(LegalAcceptance.objects.get(user__email="new@solvro.pl").version, terms)

    @patch("users.views.oauth.oauth.create_client")
    def test_new_account_can_log_in_before_any_terms_are_published(self, mock_create_client):
        self._solvro_login(mock_create_client, "early@solvro.pl")

        self.assertTrue(User.objects.filter(email="early@solvro.pl").exists())
        self.assertFalse(LegalAcceptance.objects.exists())

    @patch("users.views.oauth.oauth.create_client")
    def test_existing_account_gets_no_acceptance_on_login(self, mock_create_client):
        publish_terms()
        user = User.objects.create_user(email="existing@solvro.pl")

        self._solvro_login(mock_create_client, user.email)

        self.assertFalse(LegalAcceptance.objects.filter(user=user).exists())


@override_settings(DEBUG=True)
@patch("users.views.utils.ALLOWED_REDIRECT_ORIGINS", ["http://localhost:3000"])
class UsosSignupAcceptanceTests(APITestCase):
    def setUp(self):
        self.terms = publish_terms()

    def _usos_login(self, user, *, created):
        session = self.client.session
        session["request_token_token"] = "secret"
        session.save()

        with (
            patch("users.views.oauth.USOSClient") as client_class,
            patch("users.views.oauth.update_user_data_from_usos", AsyncMock(return_value=(user, created))),
        ):
            client = client_class.return_value.__aenter__.return_value
            client.authorize = AsyncMock(return_value=("access", "access-secret"))
            return self.client.get(
                "/api/authorize/usos/",
                {"jwt": "true", "redirect": "http://localhost:3000/", "oauth_token": "token", "oauth_verifier": "v"},
            )

    @staticmethod
    def _student(**extra):
        return User.objects.create_user(
            email="student@student.pwr.edu.pl",
            student_status=StudentStatus.ACTIVE_STUDENT.value,
            staff_status=StaffStatus.NOT_STAFF.value,
            **extra,
        )

    def test_new_student_records_the_terms_in_force(self):
        user = self._student()

        self._usos_login(user, created=True)

        self.assertEqual(LegalAcceptance.objects.get(user=user).version, self.terms)

    def test_returning_student_gets_no_acceptance_on_login(self):
        user = self._student()

        self._usos_login(user, created=False)

        self.assertFalse(LegalAcceptance.objects.filter(user=user).exists())

    def test_rejected_account_leaves_no_acceptance(self):
        user = User.objects.create_user(
            email="staff@pwr.edu.pl",
            student_status=StudentStatus.ACTIVE_STUDENT.value,
            staff_status=StaffStatus.NON_ACADEMIC_STAFF.value,
        )

        response = self._usos_login(user, created=True)

        self.assertIn("error=not_student", response.url)
        self.assertFalse(LegalAcceptance.objects.exists())


# The authorize URL ChatGPT opens: a query string whose `client_id` carries its own query string.
OAUTH_AUTHORIZE_REDIRECT = "http://localhost:3000/oauth/authorize?" + urllib.parse.urlencode(
    {
        "response_type": "code",
        "client_id": "https://chatgpt.com/oauth/4TN8Cajh8P0r/client.json?token_endpoint_auth_method=none",
        "redirect_uri": "https://chatgpt.com/connector/oauth/4TN8Cajh8P0r",
        "scope": "quizzes:read quizzes:write study:read study:write user:read",
        "code_challenge": "Ckfm2akJwOaM-vOMxeRyFOkqGnhNuLVZjcjixqZwtpU",
        "code_challenge_method": "S256",
        "resource": "https://testownik.solvro.pl/api/mcp",
        "state": "oauth_s_6b05a2260f8c8191aa863849eeb74773",
        "ui_locales": "en-US",
    }
)


def _query(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)


@override_settings(DEBUG=True)
@patch("users.views.utils.ALLOWED_REDIRECT_ORIGINS", ["http://localhost:3000"])
class OAuthAuthorizeRedirectTests(APITestCase):
    """Every sign-in method must land back on the exact OAuth authorize URL it started from."""

    def _assert_lands_on_authorize_url(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("http://localhost:3000/oauth/authorize?"))
        self.assertEqual(_query(response.url), _query(OAUTH_AUTHORIZE_REDIRECT))

    @patch("users.views.oauth.oauth.create_client")
    def test_solvro_login_returns_to_authorize_url(self, mock_create_client):
        mock_auth_client = mock_create_client.return_value
        mock_auth_client.authorize_redirect.return_value = HttpResponseRedirect("https://auth.solvro.pl/login")
        mock_auth_client.authorize_access_token.return_value = {"access_token": "mock_token"}
        mock_auth_client.get.return_value.json.return_value = {"email": "oauth@solvro.pl"}

        self.client.get(reverse("login"), {"jwt": "true", "redirect": OAUTH_AUTHORIZE_REDIRECT})
        callback_url = mock_auth_client.authorize_redirect.call_args.args[1]
        callback = urllib.parse.urlsplit(callback_url)
        response = self.client.get(callback.path, _query(callback_url))

        self._assert_lands_on_authorize_url(response)
        self.assertIn("access_token", response.cookies)

    @patch.dict("os.environ", {"USOS_CONSUMER_KEY": "key", "USOS_CONSUMER_SECRET": "secret"})
    def _usos_login(self, params):
        with patch("users.views.oauth.USOSClient") as client_class:
            client = client_class.return_value.__aenter__.return_value
            client.get_authorization_url = AsyncMock(return_value="https://apps.usos.pwr.edu.pl/authorize")
            client.set_scopes = MagicMock()
            client.connection.auth_manager.get_request_token = MagicMock(return_value=("token", "token-secret"))
            response = self.client.get(reverse("login_usos"), params)
        self.assertEqual(response.url, "https://apps.usos.pwr.edu.pl/authorize")
        return client.get_authorization_url.call_args.args[0]

    def _usos_callback(self, callback_url, user):
        with (
            patch("users.views.oauth.USOSClient") as client_class,
            patch("users.views.oauth.update_user_data_from_usos", AsyncMock(return_value=(user, False))),
        ):
            client_class.return_value.__aenter__.return_value.authorize = AsyncMock(
                return_value=("access", "access-secret")
            )
            callback = urllib.parse.urlsplit(callback_url)
            return self.client.get(
                callback.path, {**_query(callback_url), "oauth_token": "token", "oauth_verifier": "v"}
            )

    def test_usos_callback_url_has_no_percent_encoding(self):
        # USOS rejects the request token with "Invalid signature" when `oauth_callback` has any %XX.
        callback_url = self._usos_login({"jwt": "true", "redirect": OAUTH_AUTHORIZE_REDIRECT, "guest_id": "g-1"})

        self.assertNotIn("%", callback_url)
        self.assertEqual(_query(callback_url), {"jwt": ["true"], "guest_id": ["g-1"]})

    def test_usos_login_returns_to_authorize_url(self):
        student = User.objects.create_user(
            email="student@student.pwr.edu.pl",
            student_status=StudentStatus.ACTIVE_STUDENT.value,
            staff_status=StaffStatus.NOT_STAFF.value,
        )
        callback_url = self._usos_login({"jwt": "true", "redirect": OAUTH_AUTHORIZE_REDIRECT})

        response = self._usos_callback(callback_url, student)

        self._assert_lands_on_authorize_url(response)
        self.assertIn("access_token", response.cookies)

    def test_usos_retry_keeps_the_authorize_url(self):
        callback_url = self._usos_login({"jwt": "true", "redirect": OAUTH_AUTHORIZE_REDIRECT})
        session = self.client.session
        del session["request_token_token"]
        session.save()

        retry = self._usos_callback(callback_url, user=None)

        self.assertEqual(urllib.parse.urlsplit(retry.url).path, "/api/login/usos/")
        self.assertEqual(_query(retry.url)["redirect"], [OAUTH_AUTHORIZE_REDIRECT])
        self.assertEqual(_query(retry.url)["retry"], ["1"])
        retry_callback_url = self._usos_login(_query(retry.url))
        self.assertEqual(_query(retry_callback_url)["retry"], ["1"])
        self.assertEqual(self.client.session["usos_redirect_token"], OAUTH_AUTHORIZE_REDIRECT)
