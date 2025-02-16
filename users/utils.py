from django.conf import settings
from django.core.mail import EmailMessage

from users.models import EmailLoginToken


def send_login_email_to_user(user):
    user.emaillogintoken_set.all().delete()
    login_token = EmailLoginToken.create_for_user(user)

    login_link = f"https://testownik.solvro.pl/login-link/{login_token.token}"
    otp_code = login_token.otp_code

    subject = "Twój kod logowania"
    message = (
        f"Cześć {user.full_name},\n\n"
        f"Twój kod logowania: {otp_code}\n\n"
        f"Możesz także kliknąć ten link, aby się zalogować:\n"
        f"{login_link}\n\n"
        f"Ten kod i link wygasną za 10 minut."
    )

    email = EmailMessage(
        subject=subject,
        body=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.send(fail_silently=False)
