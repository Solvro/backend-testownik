import logging
import re
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _sanitize_email_header(value: str | None) -> str:
    """
    Remove control characters from a string to prevent email header injection.

    Args:
        value: The string to sanitize. Can be None.

    Returns:
        The sanitized string with control characters removed and stripped.
        Returns an empty string if the input is None.
    """
    if not value:
        return ""
    return re.sub(r"[\x00-\x1F\x7F-\x9F]", "", value).strip()


def send_email(
    subject: str,
    recipient_list: list[str],
    title: str | None = None,
    content: str | None = None,
    template_name: str | None = None,
    context: dict[str, Any] | None = None,
    cta_url: str | None = None,
    cta_text: str | None = None,
    cta_description: str | None = None,
    from_email: str | None = None,
    reply_to: list[str] | None = None,
    fail_silently: bool = True,
    connection=None,
) -> bool:
    """
    Send an email using the standardized base template.

    This function wraps the email content in the project's base email template (`emails/base.html`).
    The content can be provided as a raw HTML string or rendered from an inner template.
    It automatically handles header sanitization for the subject line and generates a plain text fallback.

    Args:
        subject: The subject line of the email. Will be sanitized.
        recipient_list: A list of email addresses to send to.
        title: The title displayed inside the email body (rendered in the base template).
        content: Raw HTML content to display. Used if `template_name` is not provided.
        template_name: Path to a Django template to render as the email body.
                       Overrides `content` if provided.
        context: Context dictionary used when rendering `template_name`.
        cta_url: URL for the Call-To-Action button. If None, no button is shown.
        cta_text: Text to display on the Call-To-Action button.
        cta_description: Optional text description displayed below the CTA button.
        from_email: The sender's email address. Defaults to `settings.DEFAULT_FROM_EMAIL`.
        reply_to: A list of email addresses to set as Reply-To header.
        fail_silently: If True, suppress exceptions raised during sending. Defaults to True.
        connection: Optional email backend connection to use for sending.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """

    if not recipient_list:
        logger.warning("Attempted to send email with no recipients.")
        return False

    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL

    # Prepare content
    final_content = content or ""
    if template_name:
        final_content = render_to_string(template_name, context or {})

    # Base template context
    base_context = {
        "title": title,
        "content": final_content,
        "cta_url": cta_url,
        "cta_text": cta_text,
        "cta_description": cta_description,
        "frontend_url": settings.FRONTEND_URL,
        # Add any other global context settings needed by base.html
    }

    html_message = render_to_string("emails/base.html", base_context)

    # Create a plain text version
    text_message = render_to_string("emails/base.txt", base_context)

    # Sanitize subject
    safe_subject = _sanitize_email_header(subject)

    email = EmailMultiAlternatives(
        subject=safe_subject,
        body=text_message,
        from_email=from_email,
        to=recipient_list,
        reply_to=reply_to,
        connection=connection,
    )
    email.attach_alternative(html_message, "text/html")

    try:
        return email.send(fail_silently=fail_silently) > 0
    except Exception as e:
        logger.error(f"Failed to send email to {recipient_list}: {e}")
        if not fail_silently:
            raise
        return False
