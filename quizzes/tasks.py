from django.apps import apps
from django.contrib.auth import get_user_model
from django.tasks import task
from django.utils.html import strip_tags

from testownik_core import settings
from testownik_core.emails import send_email


@task()
def send_quiz_shared_email_task(quiz_id: str, user_id: str):
    Quiz = apps.get_model("quizzes", "Quiz")
    User = get_user_model()

    try:
        quiz = Quiz.objects.get(id=quiz_id)
        user = User.objects.get(id=user_id)
    except (Quiz.DoesNotExist, User.DoesNotExist):
        return

    safe_title = strip_tags(quiz.title)
    safe_first_name = f" {strip_tags(user.first_name)}" if user.first_name else ""
    send_email(
        subject=f'Quiz "{safe_title}" został Ci udostępniony',
        recipient_list=[user.email],
        title=f"Cześć{safe_first_name}! 👋",
        content=f'Quiz <strong>"{safe_title}"</strong> został Ci udostępniony.',
        cta_url=f"{settings.FRONTEND_URL}/quiz/{quiz.id}",
        cta_text="Rozpocznij quiz",
        cta_description="Powodzenia! 🎓",
    )
