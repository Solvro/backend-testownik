from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.message import EmailMultiAlternatives
from django.template.loader import render_to_string

from quizzes.models import Quiz
from users.models import StudyGroup, User, UserSettings


def should_send_notification(user: User) -> bool:
    if not user.email:
        return False
    user_settings, _ = UserSettings.objects.get_or_create(user=user)
    return user_settings.notify_quiz_shared


def _sanitize_email_header(value: str | None) -> str:
    # Removes control characters that could lead to email header injection.
    if not value:
        return ""
    return value.replace("\r", "").replace("\n", "").replace("\x00", "").strip()


def _create_quiz_shared_email(quiz: Quiz, user: User, connection=None) -> EmailMultiAlternatives:
    safe_title = _sanitize_email_header(quiz.title)
    subject = f'Quiz "{safe_title}" został Ci udostępniony'
    context = {
        "user": user,
        "quiz": quiz,
        "frontend_url": settings.FRONTEND_URL,
    }
    text_message = render_to_string("emails/quiz_shared.txt", context)
    html_message = render_to_string("emails/quiz_shared.html", context)

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        connection=connection,
    )
    email.attach_alternative(html_message, "text/html")
    return email


def notify_quiz_shared_to_users(quiz: Quiz, user: User):
    if not should_send_notification(user):
        return
    email = _create_quiz_shared_email(quiz, user)
    email.send(fail_silently=True)


def notify_quiz_shared_to_groups(quiz: Quiz, group: StudyGroup):
    connection = get_connection(fail_silently=True)
    for user in group.members.all():
        if should_send_notification(user):
            email = _create_quiz_shared_email(quiz, user, connection=connection)
            email.send(fail_silently=True)
