"""Guest UUIDs identify data; only the guest's credential authorizes migration."""

# Provider calls are mocked: these tests never send auth messages or use live accounts.
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase
from usos_api.models import StaffStatus, StudentStatus

from quizzes.models import Quiz
from users.models import EmailLoginToken, User
from users.serializers import UserTokenObtainPairSerializer
from users.tests.test_oauth import _usos_client_mock


class GuestMigrationFixtures(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.owner = User.objects.create_user(email="migration-owner@example.test")
        self.victim = User.objects.create_guest_user()
        self.other_guest = User.objects.create_guest_user()
        self.quiz = Quiz.objects.create(
            title="Private guest draft", creator=self.victim, folder=self.victim.root_folder
        )

    def login(self, endpoint, *, bearer=None, cookie=None, guest=None):
        token = EmailLoginToken.create_for_user(self.owner)
        data = {"guest_id": str((guest or self.victim).pk)}
        if endpoint == "login_otp":
            data.update(email=self.owner.email, otp=token.otp_code)
        else:
            data["token"] = str(token.token)
        if bearer:
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {bearer}")
        if cookie:
            self.client.cookies["access_token"] = cookie
        response = self.client.post(reverse(endpoint), data, format="json")
        return response, token

    def assert_victim_retained(self, token):
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator_id, self.victim.pk)
        self.assertTrue(User.objects.filter(pk=self.victim.pk).exists())
        self.assertTrue(EmailLoginToken.objects.filter(pk=token.pk).exists())


class GuestMigrationAuthorizationTests(GuestMigrationFixtures):
    def test_uuid_alone_cannot_transfer_another_guest(self):
        for endpoint in ("login_otp", "login_link"):
            with self.subTest(endpoint=endpoint):
                response, token = self.login(endpoint)
                self.assertEqual(response.status_code, 403)
                self.assert_victim_retained(token)

    def test_other_guest_credential_cannot_transfer_victim(self):
        bearer = str(UserTokenObtainPairSerializer.get_token(self.other_guest).access_token)
        for endpoint in ("login_otp", "login_link"):
            with self.subTest(endpoint=endpoint):
                response, token = self.login(endpoint, bearer=bearer)
                self.assertEqual(response.status_code, 403)
                self.assert_victim_retained(token)

    def test_matching_guest_bearer_can_upgrade(self):
        bearer = str(UserTokenObtainPairSerializer.get_token(self.victim).access_token)
        response, _ = self.login("login_otp", bearer=bearer)
        self.assertEqual(response.status_code, 200)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator_id, self.owner.pk)
        self.assertFalse(User.objects.filter(pk=self.victim.pk).exists())

    def test_cookie_alone_does_not_authorize_csrf_exempt_email_login(self):
        cookie = str(UserTokenObtainPairSerializer.get_token(self.victim).access_token)
        for endpoint in ("login_otp", "login_link"):
            response, token = self.login(endpoint, cookie=cookie)
            self.assertEqual(response.status_code, 403)
            self.assert_victim_retained(token)

    def test_matching_guest_bearer_can_upgrade_with_link(self):
        bearer = str(UserTokenObtainPairSerializer.get_token(self.victim).access_token)
        response, _ = self.login("login_link", bearer=bearer)
        self.assertEqual(response.status_code, 200)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator_id, self.owner.pk)

    def test_invalid_and_non_guest_credentials_cannot_authorize_migration(self):
        refresh = UserTokenObtainPairSerializer.get_token(self.victim)
        embedded = refresh.access_token
        embedded["mobile_embed"] = True
        credentials = (
            "invalid-token",
            str(refresh),
            str(embedded),
            str(UserTokenObtainPairSerializer.get_token(self.owner).access_token),
        )
        for credential in credentials:
            with self.subTest(credential_type=credential.split(".")[0]):
                response, token = self.login("login_otp", bearer=credential)
                self.assertEqual(response.status_code, 403)
                self.assert_victim_retained(token)

    def test_no_guest_login_ignores_expired_existing_credentials(self):
        token = EmailLoginToken.create_for_user(self.owner)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid-expired-token")
        self.client.cookies["access_token"] = "invalid-expired-token"
        response = self.client.post(
            reverse("login_otp"), {"email": self.owner.email, "otp": token.otp_code}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator_id, self.victim.pk)

    @patch("users.views.email_auth.migrate_guest_to_user", return_value=False)
    def test_failed_migration_keeps_login_token_and_guest_data(self, _migration):
        bearer = str(UserTokenObtainPairSerializer.get_token(self.victim).access_token)
        response, token = self.login("login_otp", bearer=bearer)
        self.assertEqual(response.status_code, 409)
        self.assert_victim_retained(token)
        self.assertNotIn("access_token", response.cookies)

    def test_uppercase_uuid_is_accepted_as_same_identity(self):
        token = EmailLoginToken.create_for_user(self.owner)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {UserTokenObtainPairSerializer.get_token(self.victim).access_token}"
        )
        response = self.client.post(
            reverse("login_otp"),
            {"email": self.owner.email, "otp": token.otp_code, "guest_id": str(self.victim.pk).upper()},
            format="json",
        )
        self.assertEqual(response.status_code, 200)


@override_settings(DEBUG=True)
class GuestOAuthMigrationAuthorizationTests(GuestMigrationFixtures):
    def setUp(self):
        super().setUp()
        self.owner.student_status = StudentStatus.ACTIVE_STUDENT.value
        self.owner.staff_status = StaffStatus.NOT_STAFF.value
        self.owner.save()
        self.client.cookies["access_token"] = str(UserTokenObtainPairSerializer.get_token(self.victim).access_token)

    def start_solvro(self, auth):
        auth.authorize_redirect.return_value = HttpResponseRedirect("https://provider.example/login")
        response = self.client.get(reverse("login"), {"guest_id": str(self.victim.pk)})
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(auth.authorize_redirect.call_args.args[1]).query)
        self.assertNotIn("guest_id", query)
        return query["guest_migration"][0]

    def mock_profile(self, auth):
        auth.authorize_access_token.return_value = {"access_token": "fixture"}
        auth.get.return_value.json.return_value = {"email": self.owner.email}

    @patch("users.views.oauth.oauth.create_client")
    def test_start_rejects_unproven_or_different_guest(self, create_client):
        for cookie in ("", str(UserTokenObtainPairSerializer.get_token(self.other_guest).access_token)):
            self.client.cookies["access_token"] = cookie
            response = self.client.get(reverse("login"), {"guest_id": str(self.victim.pk)})
            self.assertEqual(response.status_code, 403)
        create_client.assert_not_called()

    @patch("users.views.oauth.oauth.create_client")
    def test_bad_explicit_bearer_does_not_fall_back_to_valid_guest_cookie(self, create_client):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid-token")
        response = self.client.get(reverse("login"), {"guest_id": str(self.victim.pk)})
        self.assertEqual(response.status_code, 403)
        create_client.assert_not_called()

    @patch("users.views.oauth.oauth.create_client")
    def test_callback_uuid_injection_is_rejected_before_provider_exchange(self, create_client):
        response = self.client.get(reverse("authorize"), {"guest_id": str(self.victim.pk)})
        self.assertEqual(response.status_code, 403)
        create_client.assert_not_called()
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator_id, self.victim.pk)

    @patch("users.views.oauth.enqueue_user_photo")
    @patch("users.views.oauth.oauth.create_client")
    def test_guest_proof_bound_to_session_and_guest_then_consumed_once(self, create_client, _photo):
        auth = create_client.return_value
        flow = self.start_solvro(auth)
        self.mock_profile(auth)
        # A flow URL copied to another browser grants no authority, even with guest JWT.
        other_browser = APIClient()
        other_browser.cookies["access_token"] = self.client.cookies["access_token"].value
        response = other_browser.get(reverse("authorize"), {"guest_migration": flow})
        self.assertEqual(response.status_code, 403)
        auth.authorize_access_token.assert_not_called()
        # The original session with a changed guest cookie must also fail closed.
        self.client.cookies["access_token"] = str(
            UserTokenObtainPairSerializer.get_token(self.other_guest).access_token
        )
        response = self.client.get(reverse("authorize"), {"guest_migration": flow})
        self.assertEqual(response.status_code, 403)
        auth.authorize_access_token.assert_not_called()
        self.client.cookies["access_token"] = str(UserTokenObtainPairSerializer.get_token(self.victim).access_token)
        response = self.client.get(reverse("authorize"), {"guest_migration": flow})
        self.assertEqual(response.status_code, 302)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator_id, self.owner.pk)
        auth.authorize_access_token.reset_mock()
        response = self.client.get(reverse("authorize"), {"guest_migration": flow})
        self.assertEqual(response.status_code, 403)
        auth.authorize_access_token.assert_not_called()

    @patch("users.views.oauth.oauth.create_client")
    def test_expired_flow_aborts_before_provider_exchange(self, create_client):
        flow = self.start_solvro(create_client.return_value)
        session = self.client.session
        flows = session["guest_migration_flows"]
        flows[flow]["expires"] = 0
        session["guest_migration_flows"] = flows
        session.save()
        response = self.client.get(reverse("authorize"), {"guest_migration": flow})
        self.assertEqual(response.status_code, 403)
        create_client.return_value.authorize_access_token.assert_not_called()

    @patch.dict("os.environ", {"USOS_CONSUMER_KEY": "fixture", "USOS_CONSUMER_SECRET": "fixture"})
    @patch("users.views.oauth.update_user_data_from_usos", new_callable=AsyncMock)
    @patch("users.views.oauth.USOSClient")
    def test_usos_bound_guest_flow_migrates_once(self, uses_client, update_user):
        client, uses_client.return_value = _usos_client_mock()
        client.authorize = AsyncMock(return_value=("access", "secret"))
        update_user.return_value = (self.owner, False)
        response = self.client.get(reverse("login_usos"), {"guest_id": str(self.victim.pk)})
        self.assertEqual(response.status_code, 302)
        callback = client.get_authorization_url.call_args.args[0]
        flow = parse_qs(urlparse(callback).query)["guest_migration"][0]
        self.assertNotIn("%", callback)
        response = self.client.get(
            reverse("authorize_usos"),
            {"guest_migration": flow, "oauth_token": "token", "oauth_verifier": "fixture"},
        )
        self.assertEqual(response.status_code, 302)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator_id, self.owner.pk)

    @patch.dict("os.environ", {"USOS_CONSUMER_KEY": "fixture", "USOS_CONSUMER_SECRET": "fixture"})
    @patch("users.views.oauth.update_user_data_from_usos", new_callable=AsyncMock)
    @patch("users.views.oauth.USOSClient")
    def test_usos_rejected_non_student_keeps_guest_and_does_not_migrate(self, usos_client, update_user):
        client, usos_client.return_value = _usos_client_mock()
        client.authorize = AsyncMock(return_value=("access", "secret"))
        self.owner.student_status = StudentStatus.NOT_STUDENT.value
        self.owner.save()
        update_user.return_value = (self.owner, False)
        self.client.get(reverse("login_usos"), {"guest_id": str(self.victim.pk)})
        flow = parse_qs(urlparse(client.get_authorization_url.call_args.args[0]).query)["guest_migration"][0]
        response = self.client.get(
            reverse("authorize_usos"),
            {"guest_migration": flow, "oauth_token": "token", "oauth_verifier": "fixture"},
        )
        self.assertEqual(response.status_code, 302)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.creator_id, self.victim.pk)
        self.assertTrue(User.objects.filter(pk=self.victim.pk).exists())
        self.assertNotIn(flow, self.client.session["guest_migration_flows"])

    @patch("users.views.oauth.USOSClient")
    def test_usos_uuid_injection_aborts_before_provider_exchange(self, uses_client):
        response = self.client.get(reverse("authorize_usos"), {"guest_id": str(self.victim.pk)})
        self.assertEqual(response.status_code, 403)
        uses_client.assert_not_called()

    @patch.dict("os.environ", {"USOS_CONSUMER_KEY": "fixture", "USOS_CONSUMER_SECRET": "fixture"})
    @patch("users.views.oauth.USOSClient")
    def test_usos_retry_reproves_guest_instead_of_forwarding_old_grant(self, uses_client):
        client, uses_client.return_value = _usos_client_mock()
        self.client.get(reverse("login_usos"), {"guest_id": str(self.victim.pk)})
        flow = parse_qs(urlparse(client.get_authorization_url.call_args.args[0]).query)["guest_migration"][0]
        response = self.client.get(reverse("authorize_usos"), {"guest_migration": flow, "oauth_token": "missing"})
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.url).query)
        self.assertEqual(query["guest_id"], [str(self.victim.pk)])
        self.assertNotIn("guest_migration", query)
