from unittest.mock import Mock, call, patch

from django.test import SimpleTestCase, override_settings

from testownik_core.emails import _sanitize_email_header, send_email


@override_settings(FRONTEND_URL="")
class EmailServiceTests(SimpleTestCase):
    @patch("testownik_core.emails.EmailMultiAlternatives")
    @patch("testownik_core.emails.render_to_string")
    def test_send_email_basic(self, mock_render, mock_email_cls):
        """Test sending a basic email with raw content."""

        # Setup specific returns for different template calls
        def render_side_effect(template_name, context=None):
            if template_name == "emails/base.html":
                return "<html><body>Rendered Base HTML</body></html>"
            if template_name == "emails/base.txt":
                return "Rendered Base TXT"
            return ""

        mock_render.side_effect = render_side_effect
        mock_email = Mock()
        mock_email_cls.return_value = mock_email

        send_email(
            subject="Test Subject",
            recipient_list=["test@example.com"],
            title="Test Title",
            content="<p>Test Content</p>",
            cta_url="http://example.com",
            cta_text="Click Me",
        )

        # check that render_to_string was called for both base.html and base.txt
        expected_calls = [
            call(
                "emails/base.html",
                {
                    "title": "Test Title",
                    "content": "<p>Test Content</p>",
                    "cta_url": "http://example.com",
                    "cta_text": "Click Me",
                    "cta_description": None,
                    "frontend_url": "",
                },
            ),
            call(
                "emails/base.txt",
                {
                    "title": "Test Title",
                    "content": "<p>Test Content</p>",
                    "cta_url": "http://example.com",
                    "cta_text": "Click Me",
                    "cta_description": None,
                    "frontend_url": "",
                },
            ),
        ]
        # We check that these calls were present. Note: `any_order=True` if order doesn't matter,
        # but implementation does html then txt.
        mock_render.assert_has_calls(expected_calls, any_order=True)

        # Check email creation logic
        mock_email_cls.assert_called_once()
        call_kwargs = mock_email_cls.call_args[1]
        self.assertEqual(call_kwargs["subject"], "Test Subject")
        self.assertEqual(call_kwargs["to"], ["test@example.com"])
        self.assertEqual(call_kwargs["body"], "Rendered Base TXT")

        # Check send called
        mock_email.send.assert_called_once_with(fail_silently=True)
        mock_email.attach_alternative.assert_called_once_with(
            "<html><body>Rendered Base HTML</body></html>", "text/html"
        )

    @patch("testownik_core.emails.EmailMultiAlternatives")
    @patch("testownik_core.emails.render_to_string")
    def test_send_email_with_template(self, mock_render, mock_email_cls):
        """Test sending an email using an inner template."""

        # Setup mock to return different values for different calls
        def render_side_effect(template_name, context=None):
            if template_name == "inner_template.html":
                return "<div>Inner Content</div>"
            if template_name == "emails/base.html":
                return "<html>Base HTML with Inner</html>"
            if template_name == "emails/base.txt":
                return "Base TXT with Inner"
            return ""

        mock_render.side_effect = render_side_effect
        mock_email = Mock()
        mock_email_cls.return_value = mock_email

        send_email(
            subject="Template Email",
            recipient_list=["test@example.com"],
            template_name="inner_template.html",
            context={"foo": "bar"},
        )

        # Verify inner template was rendered with context
        # Check that we rendered inner template first
        self.assertEqual(mock_render.call_args_list[0], call("inner_template.html", {"foo": "bar"}))

        # Check call for base.txt has correct content
        # We can scan through calls to find the one for base.txt
        txt_call = next(c for c in mock_render.call_args_list if c[0][0] == "emails/base.txt")
        self.assertEqual(txt_call[0][1]["content"], "<div>Inner Content</div>")

        # Check email body
        call_kwargs = mock_email_cls.call_args[1]
        self.assertEqual(call_kwargs["body"], "Base TXT with Inner")

    def test_sanitize_header(self):
        """Test header sanitization."""
        self.assertEqual(_sanitize_email_header("Test\nHeader"), "TestHeader")
        self.assertEqual(_sanitize_email_header("Test\rHeader"), "TestHeader")
        self.assertEqual(_sanitize_email_header("  Trim Me  "), "Trim Me")

    @patch("testownik_core.emails.logger")
    def test_no_recipients(self, mock_logger):
        """Test that nothing happens if recipient list is empty."""
        result = send_email("Subject", [])
        self.assertFalse(result)
        mock_logger.warning.assert_called_once()
