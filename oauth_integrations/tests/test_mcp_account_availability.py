"""MCP OAuth must honor the same account ban boundary as the REST API."""

from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from django.utils.module_loading import import_string
from oauth2_provider.models import AbstractApplication, AccessToken, get_application_model
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from quizzes.mcp import QuizTools
from quizzes.models import Quiz
from users.models import User


class MCPAccountAvailabilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="mcp-account-boundary@example.invalid")
        self.app = get_application_model().objects.create(
            name="Synthetic MCP account boundary",
            client_id="synthetic-mcp-account-boundary",
            client_type=AbstractApplication.CLIENT_PUBLIC,
            authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.invalid/callback",
        )
        self.token = AccessToken.objects.create(
            user=self.user,
            application=self.app,
            token=str(uuid4()),
            scope="quizzes:read quizzes:write",
            expires=timezone.now() + timedelta(minutes=5),
        )

    def authenticate(self):
        request = Request(APIRequestFactory().post("/api/mcp/", HTTP_AUTHORIZATION=f"Bearer {self.token.token}"))
        backend = import_string(settings.DJANGO_MCP_AUTHENTICATION_CLASSES[0])()
        return request, backend.authenticate(request)

    def authenticated_tool_request(self):
        request, result = self.authenticate()
        self.assertIsNotNone(result)
        request.user, request.auth = result
        self.assertTrue(IsAuthenticated().has_permission(request, None))
        return request

    def test_active_oauth_account_can_create_a_quiz_through_configured_mcp_auth(self):
        tools = QuizTools(request=self.authenticated_tool_request())
        result = tools.create_quiz("Active synthetic MCP fixture")
        self.assertIn("id", result)
        self.assertEqual(Quiz.objects.filter(creator=self.user).count(), 1)

    def test_preexisting_oauth_token_cannot_mutate_after_account_ban(self):
        self.user.is_banned = True
        self.user.save(update_fields=["is_banned"])
        try:
            request = self.authenticated_tool_request()
        except (AuthenticationFailed, PermissionDenied):
            request = None
        if request is not None:
            QuizTools(request=request).create_quiz("Forbidden synthetic MCP fixture")
        self.assertFalse(Quiz.objects.filter(creator=self.user).exists())
        self.assertIsNone(request, "Configured MCP authentication accepted a banned account")

    def test_banned_oauth_is_rejected_by_actual_mcp_endpoint_before_protocol_handler(self):
        self.user.is_banned = True
        self.user.save(update_fields=["is_banned"])
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token.token}")
        response = client.post("/api/mcp/", {}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(Quiz.objects.filter(creator=self.user).exists())

    def test_expired_revoked_and_deleted_account_tokens_are_not_authenticated(self):
        self.token.expires = timezone.now() - timedelta(minutes=1)
        self.token.save(update_fields=["expires"])
        self.assertIsNone(self.authenticate()[1])
        self.token.expires = timezone.now() + timedelta(minutes=5)
        self.token.save(update_fields=["expires"])
        self.token.delete()
        self.assertIsNone(self.authenticate()[1])
        self.token.pk = None
        self.token.save(force_insert=True)
        self.user.delete()
        self.assertIsNone(self.authenticate()[1])

    def test_valid_read_only_token_cannot_create_quizzes(self):
        self.token.scope = "quizzes:read"
        self.token.save(update_fields=["scope"])
        tools = QuizTools(request=self.authenticated_tool_request())
        with self.assertRaises(PermissionDenied):
            tools.create_quiz("Denied by scope")
        self.assertFalse(Quiz.objects.filter(creator=self.user).exists())
