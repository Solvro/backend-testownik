import logging

from testownik_core.emails import send_email
from users.models import User

from .models import Notification, NotificationType

logger = logging.getLogger(__name__)


def send_notification(
    user: User,
    title: str,
    content: str,
    notification_type: str = NotificationType.IN_APP,
    *,
    subject: str | None = None,
    cta_url: str | None = None,
    cta_text: str | None = None,
    cta_description: str | None = None,
    reply_to: list[str] | None = None,
    from_email: str | None = None,
    connection=None,
    fail_silently: bool = True,
) -> Notification:
    """
    Single entry point for sending a notification to a user.

    The notification is always persisted via :class:`Notification`. Depending
    on ``notification_type``, it is additionally dispatched through the
    matching transport:

    * :data:`NotificationType.IN_APP` — no transport, the record is the delivery.
    * :data:`NotificationType.EMAIL` — sent via :func:`testownik_core.emails.send_email`.
    * :data:`NotificationType.PUSH` — Web Push delivery (not yet implemented).

    All callers that need to inform a user about something MUST go through this
    function rather than calling ``send_email`` directly, so notifications are
    consistently recorded and inspectable from the admin / API.

    Args:
        user: Recipient of the notification.
        title: Short title shown in the notification list and used as the e-mail
            title/subject default.
        content: Main body of the notification.
        notification_type: One of :class:`NotificationType` values.
        subject: Custom e-mail subject. Defaults to ``title`` when not provided.
        cta_url: Optional CTA button URL for the e-mail.
        cta_text: Optional CTA button label.
        cta_description: Optional description shown beneath the CTA.
        reply_to: Optional Reply-To header for the e-mail.
        from_email: Optional From header for the e-mail.
        connection: Optional pre-opened e-mail backend connection (useful when
            sending a batch of e-mails from a background task).
        fail_silently: Whether transport errors should be swallowed.

    Returns:
        The created :class:`Notification` instance.
    """

    notification = Notification.objects.create(
        user=user,
        title=title,
        content=content,
        notification_type=notification_type,
    )

    if notification_type == NotificationType.EMAIL:
        if user.email:
            send_email(
                subject=subject or title,
                recipient_list=[user.email],
                title=title,
                content=content,
                cta_url=cta_url,
                cta_text=cta_text,
                cta_description=cta_description,
                reply_to=reply_to,
                from_email=from_email,
                connection=connection,
                fail_silently=fail_silently,
            )
        else:
            logger.warning("Skipping email notification for user %s: no email address set.", user.pk)
    elif notification_type == NotificationType.PUSH:
        # TODO: dispatch via Web Push once PushSubscription model is in place.
        logger.info("Push delivery not yet implemented; notification %s saved only.", notification.pk)

    return notification
