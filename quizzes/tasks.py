from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import get_connection
from django.tasks import task
from django.utils.html import strip_tags

from notifications.models import NotificationType
from notifications.utils import send_notification


@task()
def send_quiz_shared_emails_task(quiz_id: str, user_ids: list[str]):
    Quiz = apps.get_model("quizzes", "Quiz")
    User = get_user_model()

    try:
        quiz = Quiz.objects.get(id=quiz_id)
    except Quiz.DoesNotExist:
        return

    users = User.objects.filter(id__in=user_ids)
    if not users.exists():
        return

    safe_title = strip_tags(quiz.title)
    connection = get_connection(fail_silently=True)

    for user in users:
        safe_first_name = f" {strip_tags(user.first_name)}" if user.first_name else ""
        send_notification(
            user=user,
            title=f"Cześć{safe_first_name}! 👋",
            content=f'Quiz <strong>"{safe_title}"</strong> został Ci udostępniony.',
            notification_type=NotificationType.EMAIL,
            subject=f'Quiz "{safe_title}" został Ci udostępniony',
            cta_url=f"{settings.FRONTEND_URL}/quiz/{quiz.id}",
            cta_text="Rozpocznij quiz",
            cta_description="Powodzenia! 🎓",
            connection=connection,
        )
