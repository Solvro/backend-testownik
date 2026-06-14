import logging

from testownik_core.emails import send_email
from users.models import User

from .models import DeliveryStatus, Notification, NotificationType

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

    * :data:`NotificationType.IN_APP` — no transport, the record is the delivery
      (saved straight as :data:`DeliveryStatus.DELIVERED`).
    * :data:`NotificationType.EMAIL` — saved as :data:`DeliveryStatus.PENDING`,
      flipped to ``DELIVERED`` or ``FAILED`` after the e-mail backend reports back.
    * :data:`NotificationType.PUSH` — Web Push delivery (not yet implemented;
      stays ``PENDING`` until a real transport is wired in).

    Any e-mail transport failure is recorded on the notification itself
    (``delivery_status`` + ``delivery_error``) so it can be inspected from the
    admin / API instead of being silently lost. If ``fail_silently`` is ``False``
    the underlying exception is re-raised AFTER the failure is persisted.

    Returns:
        The created :class:`Notification` instance.
    """

    initial_status = (
        DeliveryStatus.DELIVERED if notification_type == NotificationType.IN_APP else DeliveryStatus.PENDING
    )

    notification = Notification.objects.create(
        user=user,
        title=title,
        content=content,
        notification_type=notification_type,
        delivery_status=initial_status,
    )

    if notification_type == NotificationType.EMAIL:
        _dispatch_email(
            notification,
            subject=subject,
            cta_url=cta_url,
            cta_text=cta_text,
            cta_description=cta_description,
            reply_to=reply_to,
            from_email=from_email,
            connection=connection,
            fail_silently=fail_silently,
        )
    elif notification_type == NotificationType.PUSH:
        # TODO: dispatch via Web Push once PushSubscription model is in place.
        logger.info("Push delivery not yet implemented; notification %s left pending.", notification.pk)

    return notification


def _dispatch_email(
    notification: Notification,
    *,
    subject: str | None,
    cta_url: str | None,
    cta_text: str | None,
    cta_description: str | None,
    reply_to: list[str] | None,
    from_email: str | None,
    connection,
    fail_silently: bool,
) -> None:
    """Send the e-mail for `notification` and persist the delivery result on it."""

    user = notification.user

    if not user.email:
        _mark_failed(notification, "Recipient user has no e-mail address set.")
        logger.warning("Skipping email notification for user %s: no email address set.", user.pk)
        return

    try:
        sent = send_email(
            subject=subject or notification.title,
            recipient_list=[user.email],
            title=notification.title,
            content=notification.content,
            cta_url=cta_url,
            cta_text=cta_text,
            cta_description=cta_description,
            reply_to=reply_to,
            from_email=from_email,
            connection=connection,
            fail_silently=fail_silently,
        )
    except Exception as exc:
        _mark_failed(notification, str(exc) or exc.__class__.__name__)
        raise

    if sent:
        notification.delivery_status = DeliveryStatus.DELIVERED
        notification.delivery_error = ""
        notification.save(update_fields=["delivery_status", "delivery_error", "updated_at"])
    else:
        _mark_failed(notification, "E-mail backend reported delivery failure.")


def _mark_failed(notification: Notification, error: str) -> None:
    notification.delivery_status = DeliveryStatus.FAILED
    notification.delivery_error = error
    notification.save(update_fields=["delivery_status", "delivery_error", "updated_at"])
