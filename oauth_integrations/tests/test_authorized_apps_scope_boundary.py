"""Profile consent does not authorize managing another app's OAuth grants."""

from datetime import timedelta
from uuid import uuid4

from django.urls import reverse
from django.utils import timezone
from oauth2_provider.models import AbstractApplication, AccessToken, RefreshToken, get_application_model
from rest_framework.test import APITestCase

from users.models import User
from users.serializers import UserTokenObtainPairSerializer


class AuthorizedAppsScopeBoundaryTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="grant-boundary@example.invalid")
        self.third_party = self.application("synthetic-profile-client")
        self.mobile = self.application("testownik-mobile")
        self.mobile_access = self.token(self.mobile, "user:read user:write")
        self.mobile_refresh = RefreshToken.objects.create(
            user=self.user, application=self.mobile, token=str(uuid4()), access_token=self.mobile_access
        )

    def application(self, client_id):
        return get_application_model().objects.create(
            name=client_id,
            client_id=client_id,
            client_type=AbstractApplication.CLIENT_PUBLIC,
            authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.invalid/callback",
        )

    def token(self, app, scope):
        return AccessToken.objects.create(
            user=self.user,
            application=app,
            token=str(uuid4()),
            scope=scope,
            expires=timezone.now() + timedelta(minutes=5),
        )

    def authorize(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")

    def test_third_party_profile_read_cannot_enumerate_other_authorized_apps(self):
        self.authorize(self.token(self.third_party, "user:read"))
        self.assertEqual(self.client.get(reverse("authorized_apps")).status_code, 403)

    def test_third_party_profile_write_cannot_revoke_mobile_grant(self):
        self.authorize(self.token(self.third_party, "user:write"))
        denied = self.client.delete(reverse("authorized_app_detail", kwargs={"client_id": "testownik-mobile"}))
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(AccessToken.objects.filter(pk=self.mobile_access.pk).exists())
        self.assertTrue(RefreshToken.objects.filter(pk=self.mobile_refresh.pk).exists())

    def test_mobile_can_list_and_revoke_a_third_party_grant(self):
        third_access = self.token(self.third_party, "user:read")
        self.authorize(self.mobile_access)
        self.assertEqual(self.client.get(reverse("authorized_apps")).status_code, 200)
        revoked = self.client.delete(
            reverse("authorized_app_detail", kwargs={"client_id": self.third_party.client_id})
        )
        self.assertEqual(revoked.status_code, 204)
        self.assertFalse(AccessToken.objects.filter(pk=third_access.pk).exists())
        self.assertTrue(AccessToken.objects.filter(pk=self.mobile_access.pk).exists())

    def test_existing_jwt_can_manage_its_own_connected_apps(self):
        token = UserTokenObtainPairSerializer.get_token(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.get(reverse("authorized_apps")).status_code, 200)
        self.assertEqual(
            self.client.delete(reverse("authorized_app_detail", kwargs={"client_id": "testownik-mobile"})).status_code,
            204,
        )

    def test_existing_browser_session_can_manage_its_own_connected_apps(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("authorized_apps")).status_code, 200)
        self.assertEqual(
            self.client.delete(reverse("authorized_app_detail", kwargs={"client_id": "testownik-mobile"})).status_code,
            204,
        )

    def test_token_without_application_is_denied_without_deleting_any_grant(self):
        self.authorize(self.token(None, "user:read user:write"))
        self.assertIn(self.client.get(reverse("authorized_apps")).status_code, (401, 403))
        response = self.client.delete(reverse("authorized_app_detail", kwargs={"client_id": "testownik-mobile"}))
        self.assertIn(response.status_code, (401, 403))
        self.assertTrue(AccessToken.objects.filter(pk=self.mobile_access.pk).exists())
        self.assertTrue(RefreshToken.objects.filter(pk=self.mobile_refresh.pk).exists())

    def test_third_party_can_still_revoke_its_own_token_normally(self):
        token = self.token(self.third_party, "user:read user:write")
        response = self.client.post(
            "/api/oauth/revoke_token/",
            {"client_id": self.third_party.client_id, "token": token.token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AccessToken.objects.filter(pk=token.pk).exists())
        self.assertTrue(AccessToken.objects.filter(pk=self.mobile_access.pk).exists())
        self.assertTrue(RefreshToken.objects.filter(pk=self.mobile_refresh.pk).exists())
