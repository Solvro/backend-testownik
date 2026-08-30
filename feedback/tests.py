from unittest.mock import patch

from rest_framework.test import APITestCase


class FeedbackErrorsTests(APITestCase):
    @patch("feedback.views.N8N_WEBHOOK", None)
    def test_missing_webhook_returns_standardized_server_error(self):
        self.client.raise_request_exception = False
        response = self.client.post(
            "/api/feedback/send",
            {"name": "Test User", "title": "Feedback", "content": "Test content"},
            format="json",
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["type"], "server_error")
        self.assertEqual(response.data["errors"][0]["code"], "error")
        self.assertIn("detail", response.data["errors"][0])
        self.assertIsNone(response.data["errors"][0]["attr"])
