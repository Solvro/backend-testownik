from django.conf import settings
from django.utils.html import strip_tags

from notifications.models import NotificationType
from notifications.utils import send_notification
from users.models import EmailLoginToken


def send_login_email_to_user(user):
    user.emaillogintoken_set.all().delete()
    login_token = EmailLoginToken.create_for_user(user)

    login_link = f"{settings.FRONTEND_URL}/auth/login-link?token={login_token.token}"
    otp_code = login_token.otp_code

    subject = f"Twój kod logowania: {otp_code}"
    safe_first_name = f" {strip_tags(user.first_name)}" if user.first_name else ""

    content = (
        f"Cześć{safe_first_name}! 👋\n"
        f'Wpisz kod "{otp_code}" na stronie.\n'
        f"Możesz też kliknąć przycisk poniżej, aby się zalogować.\n"
        f"Ten kod i link wygasną za 10 minut."
    )

    send_notification(
        user=user,
        title=subject,
        content=content,
        notification_type=NotificationType.EMAIL,
        cta_url=login_link,
        cta_text="Zaloguj się",
        fail_silently=True,
    )
