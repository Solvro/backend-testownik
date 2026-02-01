"""
Tests for JWT token serializers and cookie-based authentication.
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.exceptions import InvalidToken

from users.models import EmailLoginToken, User
from users.serializers import UserTokenObtainPairSerializer, UserTokenRefreshSerializer


class UserTokenObtainPairSerializerTestCase(TestCase):
    """Tests for UserTokenObtainPairSerializer custom claims."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
            password="testpassword123",
        )

        self.staff_user = User.objects.create_user(
            email="staff@example.com",
            first_name="Staff",
            last_name="Member",
            student_number="654321",
            is_staff=True,
            is_superuser=True,
            password="testpassword123",
        )

    def test_custom_claims_embedded_in_token(self):
        """Test that custom user claims are embedded in the access token."""
        token = UserTokenObtainPairSerializer.get_token(self.user)

        # Verify all custom claims are present
        self.assertEqual(token["first_name"], "Test")
        self.assertEqual(token["last_name"], "User")
        self.assertEqual(token["full_name"], self.user.full_name)
        self.assertEqual(token["email"], "test@example.com")
        self.assertEqual(token["student_number"], "123456")
        self.assertEqual(token["photo"], self.user.photo)
        self.assertFalse(token["is_staff"])
        self.assertFalse(token["is_superuser"])

    def test_staff_flags_in_token(self):
        """Test that is_staff and is_superuser flags are correctly embedded."""
        token = UserTokenObtainPairSerializer.get_token(self.staff_user)

        self.assertTrue(token["is_staff"])
        self.assertTrue(token["is_superuser"])

    def test_access_token_contains_custom_claims(self):
        """Test that the access token payload contains custom claims."""
        token = UserTokenObtainPairSerializer.get_token(self.user)
        access_token = token.access_token

        # Access token should contain the same claims
        self.assertEqual(access_token["first_name"], "Test")
        self.assertEqual(access_token["email"], "test@example.com")


class UserTokenRefreshSerializerTestCase(TestCase):
    """Tests for UserTokenRefreshSerializer functionality."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
            password="testpassword123",
        )

    def test_refresh_repopulates_user_data(self):
        """Test that token refresh repopulates user data in the new access token."""
        # Get initial tokens
        refresh = UserTokenObtainPairSerializer.get_token(self.user)

        # Update user data
        self.user.first_name = "Updated"
        self.user.save()

        # Refresh the token
        serializer = UserTokenRefreshSerializer(data={"refresh": str(refresh)})
        self.assertTrue(serializer.is_valid())
        data = serializer.validated_data

        # Decode the new access token and verify updated data
        from rest_framework_simplejwt.tokens import AccessToken

        new_access = AccessToken(data["access"])
        self.assertEqual(new_access["first_name"], "Updated")

    def test_refresh_raises_error_for_deleted_user(self):
        """Test that refreshing a token for a deleted user raises InvalidToken."""
        # Get tokens for user
        refresh = UserTokenObtainPairSerializer.get_token(self.user)

        # Delete the user
        self.user.delete()

        # Attempt to refresh - should raise InvalidToken
        serializer = UserTokenRefreshSerializer(data={"refresh": str(refresh)})
        with self.assertRaises(InvalidToken) as context:
            serializer.is_valid(raise_exception=True)

        self.assertIn("no longer exists", str(context.exception.detail))


class CustomTokenViewsTestCase(APITestCase):
    """Tests for CustomTokenObtainPairView and CustomTokenRefreshView."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
            password="testpassword123",
        )

    def test_token_obtain_sets_cookies(self):
        """Test that token obtain endpoint sets JWT cookies."""
        url = reverse("token_obtain_pair")
        response = self.client.post(
            url,
            {"email": "test@example.com", "password": "testpassword123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify cookies are set
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

        # Verify response body contains success message, not tokens
        self.assertEqual(response.data.get("message"), "Login successful")
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)

    def test_token_obtain_cookie_properties(self):
        """Test that JWT cookies have correct security properties."""
        url = reverse("token_obtain_pair")
        response = self.client.post(
            url,
            {"email": "test@example.com", "password": "testpassword123"},
            format="json",
        )

        # Refresh token should be httpOnly
        refresh_cookie = response.cookies.get("refresh_token")
        self.assertTrue(refresh_cookie["httponly"])

        # Access token should NOT be httpOnly (client needs to read it)
        access_cookie = response.cookies.get("access_token")
        self.assertFalse(access_cookie["httponly"])

    def test_token_refresh_sets_cookies(self):
        """Test that token refresh endpoint sets JWT cookies."""
        # First obtain tokens
        refresh = UserTokenObtainPairSerializer.get_token(self.user)

        url = reverse("token_refresh")
        response = self.client.post(url, {"refresh": str(refresh)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify cookies are set
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

        # Verify response body contains success message
        self.assertEqual(response.data.get("message"), "Token refreshed")

    def test_token_obtain_with_invalid_credentials(self):
        """Test that invalid credentials don't set cookies."""
        url = reverse("token_obtain_pair")
        response = self.client.post(
            url,
            {"email": "test@example.com", "password": "wrongpassword"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Cookies should NOT be set on failure
        self.assertNotIn("access_token", response.cookies)
        self.assertNotIn("refresh_token", response.cookies)

    def test_token_refresh_with_deleted_user(self):
        """Test that refreshing token for deleted user returns 401."""
        refresh = UserTokenObtainPairSerializer.get_token(self.user)
        self.user.delete()

        url = reverse("token_refresh")
        response = self.client.post(url, {"refresh": str(refresh)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class OTPLoginCookieTestCase(APITestCase):
    """Tests for OTP login cookie setting."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
            password="testpassword123",
        )

    def test_otp_login_sets_cookies(self):
        """Test that OTP login sets JWT cookies."""
        from users.models import EmailLoginToken

        # Create a valid OTP token
        token = EmailLoginToken.create_for_user(self.user)

        url = reverse("login_otp")
        response = self.client.post(
            url,
            {"email": "test@example.com", "otp": token.otp_code},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify cookies are set
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

        # Verify response body contains success message
        self.assertEqual(response.data.get("message"), "Login successful")

    def test_link_login_sets_cookies(self):
        """Test that link login sets JWT cookies."""
        from users.models import EmailLoginToken

        # Create a valid link token
        token = EmailLoginToken.create_for_user(self.user)

        url = reverse("login_link")
        response = self.client.post(
            url,
            {"token": str(token.token)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify cookies are set
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

        # Verify response body contains success message
        self.assertEqual(response.data.get("message"), "Login successful")


class BannedUserTestCase(APITestCase):
    """Tests for banned user functionality."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            student_number="123456",
            password="testpassword123",
        )
        self.banned_user = User.objects.create_user(
            email="banned@example.com",
            first_name="Banned",
            last_name="User",
            student_number="654321",
            password="testpassword123",
            is_banned=True,
            ban_reason="Violated terms of service",
        )

    def test_token_obtain_banned_user_returns_custom_error(self):
        """Test that logging in as a banned user returns custom error message."""
        url = reverse("token_obtain_pair")
        data = {
            "email": self.banned_user.email,
            "password": "testpassword123",
        }
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("user_banned", str(response.data))
        self.assertIn("Violated terms of service", str(response.data))

    def test_token_refresh_banned_user_returns_401(self):
        """Test that refreshing token for a banned user returns 401 with ban info."""
        refresh = UserTokenObtainPairSerializer.get_token(self.banned_user)

        url = reverse("token_refresh")
        response = self.client.post(url, {"refresh": str(refresh)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("user_banned", str(response.data))

    def test_banned_user_cannot_access_protected_endpoints(self):
        """Test that banned users get 401 when accessing protected endpoints.

        Note: With is_active=False for banned users, JWT authentication rejects
        the user at the auth layer before permissions are even checked.
        """
        # First get a valid token for the banned user
        refresh = UserTokenObtainPairSerializer.get_token(self.banned_user)
        access_token = str(refresh.access_token)

        # Try to access a protected endpoint
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        url = reverse("api_current_user")
        response = self.client.get(url)

        # Auth layer blocks with 401, not permission layer with 403
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_banned_user_can_access_protected_endpoints(self):
        """Test that non-banned users can access protected endpoints normally."""
        refresh = UserTokenObtainPairSerializer.get_token(self.user)
        access_token = str(refresh.access_token)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        url = reverse("api_current_user")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_is_banned_claim_in_token(self):
        """Test that is_banned is included in JWT token claims."""
        # Non-banned user
        token = UserTokenObtainPairSerializer.get_token(self.user)
        self.assertFalse(token["is_banned"])

        # Banned user
        banned_token = UserTokenObtainPairSerializer.get_token(self.banned_user)
        self.assertTrue(banned_token["is_banned"])

    def test_unban_user_allows_access(self):
        """Test that unbanning a user restores their access."""
        # Unban the user
        self.banned_user.is_banned = False
        self.banned_user.ban_reason = None
        self.banned_user.save()

        # Get a new token
        refresh = UserTokenObtainPairSerializer.get_token(self.banned_user)
        access_token = str(refresh.access_token)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        url = reverse("api_current_user")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_otp_banned_user_returns_error(self):
        """Test that OTP login for banned user returns 403 and custom error."""
        # Create OTP token
        token = EmailLoginToken.create_for_user(self.banned_user)

        url = reverse("login_otp")
        response = self.client.post(
            url,
            {"email": self.banned_user.email, "otp": token.otp_code},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("user_banned", str(response.data))
        self.assertIn(self.banned_user.ban_reason, str(response.data))

    def test_login_link_banned_user_returns_error(self):
        """Test that magic link login for banned user returns 403 and custom error."""
        # Create Link token
        token = EmailLoginToken.create_for_user(self.banned_user)

        url = reverse("login_link")
        response = self.client.post(
            url,
            {"token": str(token.token)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("user_banned", str(response.data))
        self.assertIn(self.banned_user.ban_reason, str(response.data))
