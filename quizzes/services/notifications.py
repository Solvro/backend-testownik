from quizzes.models import Quiz
from quizzes.tasks import send_quiz_shared_emails_task
from users.models import StudyGroup, User, UserSettings


def should_send_notification(user: User) -> bool:
    if not user.email:
        return False
    user_settings, _ = UserSettings.objects.get_or_create(user=user)
    return user_settings.notify_quiz_shared


def notify_quiz_shared_to_users(quiz: Quiz, user: User):
    if not should_send_notification(user):
        return
    send_quiz_shared_emails_task.enqueue(str(quiz.id), [str(user.id)])


def notify_quiz_shared_to_groups(quiz: Quiz, group: StudyGroup):
    user_ids = [str(user.id) for user in group.members.all() if should_send_notification(user)]
    if user_ids:
        send_quiz_shared_emails_task.enqueue(str(quiz.id), user_ids)
