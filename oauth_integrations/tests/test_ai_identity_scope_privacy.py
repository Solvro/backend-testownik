"""AI access alone does not grant the personal profile scope."""

from datetime import timedelta
from uuid import uuid4

from django.utils import timezone
from oauth2_provider.models import AbstractApplication, AccessToken, get_application_model
from rest_framework.test import APITestCase

from users.models import User
from users.serializers import UserTokenObtainPairSerializer


class AIIdentityScopePrivacyTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="ai-scope-privacy@example.invalid",
            first_name="Synthetic",
            last_name="PrivacyFixture",
            student_number="900019",
        )
        self.application = get_application_model().objects.create(
            name="Synthetic AI client",
            client_id="synthetic-ai-scope-privacy",
            client_type=AbstractApplication.CLIENT_PUBLIC,
            authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.invalid/callback",
        )

    def authorize(self, scope, *, expired=False):
        token = AccessToken.objects.create(
            user=self.user,
            application=self.application,
            token=str(uuid4()),
            scope=scope,
            expires=timezone.now() + timedelta(minutes=-5 if expired else 5),
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        return token

    def test_ai_only_grant_resolves_ai_principal_without_personal_profile(self):
        self.authorize("ai:write")
        self.assertEqual(self.client.get("/api/user/").status_code, 403)
        identity = self.client.get("/api/oauth/identity/")
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.data["user_id"], str(self.user.pk))
        self.assertEqual(identity.data["account_type"], self.user.account_type)
        self.assertEqual(
            set(identity.data),
            {"user_id", "account_type", "token_type", "exp", "iat", "jti"},
        )

    def test_profile_scope_preserves_consented_identity_fields(self):
        self.authorize("ai:write user:read")
        identity = self.client.get("/api/oauth/identity/")
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.data["email"], self.user.email)
        self.assertEqual(identity.data["student_number"], self.user.student_number)
        self.assertEqual(identity.data["full_name"], self.user.full_name)

    def test_profile_write_without_read_does_not_disclose_profile(self):
        self.authorize("ai:write user:write")
        identity = self.client.get("/api/oauth/identity/")
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(
            set(identity.data),
            {"user_id", "account_type", "token_type", "exp", "iat", "jti"},
        )

    def test_existing_signed_jwt_identity_keeps_full_profile(self):
        token = UserTokenObtainPairSerializer.get_token(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        identity = self.client.get("/api/oauth/identity/")
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.data["email"], self.user.email)
        self.assertEqual(identity.data["student_number"], self.user.student_number)

    def test_first_party_full_mobile_grant_preserves_ai_identity_contract(self):
        self.application.client_id = "testownik-mobile"
        self.application.save(update_fields=["client_id"])
        self.authorize("ai:read ai:write user:read user:write study:read study:write quizzes:read quizzes:write")
        identity = self.client.get("/api/oauth/identity/")
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.data["email"], self.user.email)
        self.assertEqual(identity.data["account_level"], self.user.account_level)
        self.assertEqual(identity.data["is_superuser"], self.user.is_superuser)

    def test_anonymous_expired_revoked_and_read_only_tokens_cannot_resolve_identity(self):
        self.assertEqual(self.client.get("/api/oauth/identity/").status_code, 401)
        self.authorize("ai:write", expired=True)
        self.assertEqual(self.client.get("/api/oauth/identity/").status_code, 401)
        token = self.authorize("ai:write")
        token.delete()
        self.assertEqual(self.client.get("/api/oauth/identity/").status_code, 401)
        self.authorize("ai:read user:read")
        self.assertEqual(self.client.get("/api/oauth/identity/").status_code, 403)
