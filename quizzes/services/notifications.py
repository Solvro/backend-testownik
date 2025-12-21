from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.message import EmailMultiAlternatives
from django.template.loader import render_to_string


def should_send_notification(user):
    if not user.email:
        return False
    if hasattr(user, "settings"):
        return user.settings.notify_quiz_shared
    return True  # domyślnie True jeśli brak ustawień (tak jak w modelu user)


def _sanitize_email_header(value):
    # Removes control characters that could lead to email header injection.
    if not value:
        return ""
    return value.replace("\r", "").replace("\n", "").replace("\x00", "").strip()


def _create_quiz_shared_email(quiz, user):
    safe_title = _sanitize_email_header(quiz.title)
    subject = f'Quiz "{safe_title}" został Ci udostępniony'
    context = {
        "user": user,
        "quiz": quiz,
    }
    text_message = render_to_string("emails/quiz_shared.txt", context)
    html_message = render_to_string("emails/quiz_shared.html", context)

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.attach_alternative(html_message, "text/html")
    return email


def notify_quiz_shared_to_users(quiz, user):
    if not should_send_notification(user):
        return
    email = _create_quiz_shared_email(quiz, user)
    email.send(fail_silently=True)


def notify_quiz_shared_to_groups(quiz, group):
    connection = get_connection(fail_silently=True)
    for user in group.members.all():
        if should_send_notification(user):
            email = _create_quiz_shared_email(quiz, user)
            email.send(fail_silently=True, connection=connection)
