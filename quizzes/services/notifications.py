from django.db.models import Q

from quizzes.models import Comment, Quiz
from quizzes.tasks import send_question_comment_emails_task, send_quiz_shared_emails_task
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


def should_send_bug_report_notification(user: User) -> bool:
    if not user.email:
        return False
    user_settings, _ = UserSettings.objects.get_or_create(user=user)
    return user_settings.notify_bug_reported


def get_comment_notification_recipients(comment: Comment):
    quiz = comment.quiz
    users = User.objects.filter(
        Q(id=quiz.folder.owner_id)
        | Q(shared_folders__folder=quiz.folder, shared_folders__allow_edit=True)
        | Q(study_groups__shared_folders__folder=quiz.folder, study_groups__shared_folders__allow_edit=True)
        | Q(shared_quizzes__quiz=quiz, shared_quizzes__allow_edit=True)
        | Q(study_groups__shared_quizzes__quiz=quiz, study_groups__shared_quizzes__allow_edit=True)
    ).distinct()

    if comment.author_id:
        users = users.exclude(id=comment.author_id)

    return [user for user in users if should_send_bug_report_notification(user)]


def notify_question_comment_created(comment: Comment):
    user_ids = [str(user.id) for user in get_comment_notification_recipients(comment)]
    if user_ids:
        send_question_comment_emails_task.enqueue(str(comment.id), user_ids)
