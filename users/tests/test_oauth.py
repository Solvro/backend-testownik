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
