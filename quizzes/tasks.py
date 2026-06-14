import urllib.parse

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import get_connection
from django.tasks import task
from django.utils.html import strip_tags

from testownik_core.emails import send_email


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
        send_email(
            subject=f'Quiz "{safe_title}" został Ci udostępniony',
            recipient_list=[user.email],
            title=f"Cześć{safe_first_name}! 👋",
            content=f'Quiz <strong>"{safe_title}"</strong> został Ci udostępniony.',
            cta_url=f"{settings.FRONTEND_URL}/quiz/{quiz.id}",
            cta_text="Rozpocznij quiz",
            cta_description="Powodzenia! 🎓",
            connection=connection,
        )


@task()
def send_question_comment_emails_task(comment_id: str, user_ids: list[str]):
    Comment = apps.get_model("quizzes", "Comment")
    User = get_user_model()

    try:
        comment = Comment.objects.select_related("author", "quiz", "question").get(id=comment_id)
    except Comment.DoesNotExist:
        return

    users = User.objects.filter(id__in=user_ids)
    if not users.exists():
        return

    safe_title = strip_tags(comment.quiz.title)
    safe_question = strip_tags(comment.question.text) if comment.question else None
    safe_author = strip_tags(comment.author.full_name) if comment.author else "Ktos"
    safe_content = strip_tags(comment.content)

    query_params = {}
    if comment.question_id:
        query_params["scroll_to"] = f"question-{comment.question_id}"
    query = f"?{urllib.parse.urlencode(query_params)}" if query_params else ""
    cta_url = f"{settings.FRONTEND_URL}/edit-quiz/{comment.quiz_id}/{query}"

    if safe_question:
        content = (
            f"{safe_author} dodal komentarz do pytania "
            f'<strong>"{safe_question}"</strong> w quizie <strong>"{safe_title}"</strong>.<br><br>'
            f"{safe_content}"
        )
    else:
        content = f'{safe_author} dodal komentarz w quizie <strong>"{safe_title}"</strong>.<br><br>{safe_content}'

    connection = get_connection(fail_silently=True)
    for user in users:
        send_email(
            subject=f'Nowy komentarz w quizie "{safe_title}"',
            recipient_list=[user.email],
            title="Nowy komentarz do sprawdzenia",
            content=content,
            cta_url=cta_url,
            cta_text="Przejdz do edycji",
            connection=connection,
        )
