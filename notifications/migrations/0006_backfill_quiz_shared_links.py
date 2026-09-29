import re
from datetime import timedelta

from django.conf import settings
from django.db import migrations
from django.db.models import Q
from django.utils.html import strip_tags

# The text quizzes.tasks.send_quiz_shared_emails_task stored before notifications had links.
SHARED_QUIZ = re.compile(r'^Quiz <strong>"(?P<title>.*)"</strong> został Ci udostępniony\.$', re.DOTALL)
BATCH = timedelta(seconds=5)


def backfill_links(apps, schema_editor):
    """Point older "quiz shared with you" notifications at the quiz they announced."""
    Notification = apps.get_model("notifications", "Notification")
    SharedQuiz = apps.get_model("quizzes", "SharedQuiz")
    frontend_url = settings.FRONTEND_URL.rstrip("/")

    def quizzes_titled(title, shares):
        return {share.quiz_id for share in shares.select_related("quiz") if strip_tags(share.quiz.title) == title}

    pending = Notification.objects.filter(link="", content__endswith="został Ci udostępniony.")
    for notification in pending.iterator():
        match = SHARED_QUIZ.match(notification.content)
        if match is None:
            continue
        direct = SharedQuiz.objects.filter(user_id=notification.user_id)
        via_group = SharedQuiz.objects.filter(study_group__members__id=notification.user_id)
        # A group share notified its members in one batch; a direct share, one person.
        batch = (
            Notification.objects.filter(
                content=notification.content,
                created_at__range=(notification.created_at - BATCH, notification.created_at + BATCH),
            )
            .exclude(user_id=notification.user_id)
            .exists()
        )
        quiz_ids = quizzes_titled(match["title"], via_group if batch else direct)
        if len(quiz_ids) != 1:
            quiz_ids = quizzes_titled(match["title"], direct | via_group)
        # Skip ambiguous titles rather than guess.
        if len(quiz_ids) == 1:
            notification.link = f"{frontend_url}/quiz/{quiz_ids.pop()}"
            notification.save(update_fields=["link"])


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0005_notification_link"),
        ("quizzes", "0034_quiz_shortcut"),
    ]

    operations = [
        migrations.RunPython(backfill_links, migrations.RunPython.noop),
    ]
