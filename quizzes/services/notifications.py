from django.conf import settings
from django.core.mail import get_connection
from django.utils.html import strip_tags

from quizzes.models import Quiz
from testownik_core.emails import send_email
from users.models import StudyGroup, User, UserSettings


def should_send_notification(user: User) -> bool:
    if not user.email:
        return False
    user_settings, _ = UserSettings.objects.get_or_create(user=user)
    return user_settings.notify_quiz_shared


def _send_quiz_shared_email(quiz: Quiz, user: User, connection=None) -> bool:
    safe_title = strip_tags(quiz.title)

    return send_email(
        subject=f'Quiz "{safe_title}" został Ci udostępniony',
        recipient_list=[user.email],
        title=f"Cześć {user.first_name or 'Użytkowniku'}! 👋",
        content=f'Quiz <strong>"{safe_title}"</strong> został Ci udostępniony.',
        cta_url=f"{settings.FRONTEND_URL}/quiz/{quiz.id}",
        cta_text="Rozpocznij quiz",
        cta_description="Powodzenia! 🎓",
        connection=connection,
    )


def notify_quiz_shared_to_users(quiz: Quiz, user: User):
    if not should_send_notification(user):
        return
    _send_quiz_shared_email(quiz, user)


def notify_quiz_shared_to_groups(quiz: Quiz, group: StudyGroup):
    connection = get_connection(fail_silently=True)
    for user in group.members.all():
        if should_send_notification(user):
            _send_quiz_shared_email(quiz, user, connection=connection)
