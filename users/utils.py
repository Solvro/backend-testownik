from django.conf import settings

from testownik_core.emails import send_email
from users.models import EmailLoginToken


def send_login_email_to_user(user):
    user.emaillogintoken_set.all().delete()
    login_token = EmailLoginToken.create_for_user(user)

    login_link = f"{settings.FRONTEND_URL}/login-link/{login_token.token}"
    otp_code = login_token.otp_code

    subject = f"Twój kod logowania: {otp_code}"
    content = (
        f"Cześć{' ' + user.first_name if user.first_name else ''},\n"
        f'Wpisz kod "{otp_code}" na stronie.\n'
        f"Możesz też kliknąć przycisk poniżej, aby się zalogować.\n"
        f"Ten kod i link wygasną za 10 minut."
    )

    send_email(
        subject=subject,
        recipient_list=[user.email],
        title=subject,
        content=content,
        cta_url=login_link,
        cta_text="Zaloguj się",
        fail_silently=True,
    )
