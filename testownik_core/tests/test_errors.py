from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APITestCase


class StandardizedErrorsTests(APITestCase):
    def test_400_bad_request_returns_standardized_envelope(self):
        response = self.client.post("/api/token/", {})

        self.assertEqual(response.status_code, 400)
        data = response.json()

        self.assertEqual(data["type"], "validation_error")
        self.assertIsInstance(data["errors"], list)
        self.assertGreater(len(data["errors"]), 0)

        error = data["errors"][0]

        self.assertIn("code", error)
        self.assertIn("detail", error)
        self.assertIn("attr", error)

    def test_401_unauthorized_returns_standardized_envelope(self):
        response = self.client.get("/api/quizzes/")

        self.assertEqual(response.status_code, 401)
        data = response.json()

        self.assertEqual(data["type"], "client_error")

        error = data["errors"][0]
        self.assertEqual(error["code"], "not_authenticated")
        self.assertIn("detail", error)
        self.assertIn("attr", error)

    def test_403_forbidden_returns_standardized_envelope(self):
        User = get_user_model()
        user = User.objects.create_user(email="test_403@example.com", password="testpassword")
        self.client.force_authenticate(user=user)

        with patch("oauth_integrations.views.AuthorizedAppsViewSet.list", side_effect=PermissionDenied):
            response = self.client.get("/api/oauth/authorized-apps/")

            self.assertEqual(response.status_code, 403)
            data = response.json()

            self.assertEqual(data["type"], "client_error")

            error = data["errors"][0]
            self.assertEqual(error["code"], "permission_denied")
            self.assertIn("detail", error)
            self.assertIn("attr", error)

    def test_404_not_found_returns_standardized_envelope(self):
        response = self.client.get("/api/quizzes/does_not_exist/")

        self.assertEqual(response.status_code, 404)
        data = response.json()

        self.assertEqual(data["type"], "client_error")
        self.assertIsInstance(data["errors"], list)
        self.assertGreater(len(data["errors"]), 0)

        error = data["errors"][0]
        self.assertEqual(error["code"], "not_found")
        self.assertIn("detail", error)
        self.assertIn("attr", error)
