from django.db.models import Q

from quizzes.models import Quiz, SharedQuiz
from quizzes.tasks import send_quiz_shared_emails_task
from users.models import StudyGroup, User, UserSettings


def should_send_notification(user: User) -> bool:
    if not user.email:
        return False
    user_settings, _ = UserSettings.objects.get_or_create(user=user)
    return user_settings.notify_quiz_shared


def users_with_access(quiz: Quiz) -> set:
    """IDs of people who can already open ``quiz`` (its creator and everyone it is shared with)."""
    shares = SharedQuiz.objects.filter(quiz=quiz)
    return set(
        User.objects.filter(
            Q(pk=quiz.creator_id) | Q(shared_quizzes__in=shares) | Q(study_groups__shared_quizzes__in=shares)
        ).values_list("pk", flat=True)
    )


def notify_quiz_shared_to_users(quiz: Quiz, user: User, already_shared: set | frozenset = frozenset()):
    # Someone who could already open the quiz (e.g. through a group) isn't told again.
    if user.pk in already_shared or not should_send_notification(user):
        return
    send_quiz_shared_emails_task.enqueue(str(quiz.id), [str(user.id)])


def notify_quiz_shared_to_groups(quiz: Quiz, group: StudyGroup, already_shared: set | frozenset = frozenset()):
    user_ids = [
        str(user.id) for user in group.members.all() if user.pk not in already_shared and should_send_notification(user)
    ]
    if user_ids:
        send_quiz_shared_emails_task.enqueue(str(quiz.id), user_ids)
