"""A stalled feedback webhook must have a bounded wait and a retryable error."""

from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from rest_framework.test import APITestCase


class FeedbackWebhookTimeoutTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.payload = {
            "name": "Synthetic QA",
            "email": "feedback-fixture@example.invalid",
            "title": "Synthetic feedback",
            "content": "Fixture only",
            "diagnostic": "Synthetic diagnostic",
            "reportType": "feedback",
        }

    def tearDown(self):
        cache.clear()

    def send_with(self, upstream):
        with (
            patch("feedback.views.N8N_WEBHOOK", "https://feedback.example.invalid/hook"),
            patch("feedback.views.FEEDBACK_SECRET", "synthetic-fixture-secret"),
            patch("feedback.views.requests.post", upstream),
        ):
            return self.client.post("/api/feedback/send", self.payload, format="json")

    def test_nonresponding_webhook_is_bounded_and_returns_recoverable_error(self):
        marker = "synthetic-private-feedback-marker"
        upstream = Mock(side_effect=requests.Timeout(marker))
        with self.assertLogs("feedback.views", level="WARNING") as logs:
            response = self.send_with(upstream)
        self.assertEqual(upstream.call_count, 1)
        timeout = upstream.call_args.kwargs.get("timeout")
        self.assertIsNotNone(timeout, "Webhook call can wait indefinitely after the mobile request times out")
        self.assertIsInstance(timeout, tuple)
        self.assertEqual(len(timeout), 2)
        self.assertTrue(all(0 < value <= 20 for value in timeout))
        self.assertEqual(response.status_code, 503)
        self.assertIn("Please try again", response.data["detail"])
        self.assertNotIn("synthetic-fixture-secret", str(response.data))
        self.assertNotIn(marker, str(logs.output))
        self.assertNotIn(marker, str(response.data))

    def test_connection_failure_is_recoverable_without_logging_upstream_details(self):
        marker = "synthetic-private-webhook-token"
        upstream = Mock(side_effect=requests.ConnectionError(marker))
        with self.assertLogs("feedback.views", level="WARNING") as logs:
            response = self.send_with(upstream)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(marker, str(logs.output))
        self.assertNotIn(marker, str(response.data))

    def test_upstream_error_response_does_not_log_its_body(self):
        marker = "synthetic-private-feedback-body"
        upstream = Mock(return_value=Mock(ok=False, status_code=500, text=marker))
        with self.assertLogs("feedback.views", level="ERROR") as logs:
            response = self.send_with(upstream)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(marker, str(logs.output))
        self.assertNotIn(marker, str(response.data))

    def test_successful_webhook_preserves_existing_feedback_response(self):
        upstream = Mock(return_value=Mock(ok=True))
        response = self.send_with(upstream)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"success": "Feedback sent successfully"})
        self.assertEqual(upstream.call_args.args, ("https://feedback.example.invalid/hook",))
        self.assertEqual(upstream.call_args.kwargs["data"], {**self.payload, "secret": "synthetic-fixture-secret"})
