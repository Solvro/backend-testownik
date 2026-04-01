import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from users.models import AccountType, User

logger = logging.getLogger(__name__)


def migrate_guest_to_user(guest_id: str, target_user: User) -> bool:
    """
    Migrate all data from a guest account to the target user account, then delete the guest.

    Transfers:
    - Quizzes (creator)
    - Quiz sessions (where target doesn't already have one for that quiz)
    - Folders (owner)

    Only works when the source account is of type GUEST.
    Returns True on success, False on any failure.
    """
    if not guest_id:
        return False

    try:
        guest = User.objects.get(id=guest_id)
    except (User.DoesNotExist, ValidationError, ValueError):
        logger.warning("Guest migration: guest user %s not found", guest_id)
        return False

    if guest.account_type != AccountType.GUEST:
        logger.warning(
            "Guest migration: refused — user %s is not a guest account (type: %s)",
            guest_id,
            guest.account_type,
        )
        return False

    if guest.id == target_user.id:
        logger.warning("Guest migration: source and target are the same user %s", guest_id)
        return False

    try:
        with transaction.atomic():
            from quizzes.models import Folder, Quiz, QuizSession

            Quiz.objects.filter(creator=guest).update(creator=target_user)

            guest_active_sessions = {s.quiz_id: s for s in QuizSession.objects.filter(user=guest, is_active=True)}
            target_active_sessions = {
                s.quiz_id: s for s in QuizSession.objects.filter(user=target_user, is_active=True)
            }

            to_archive = [
                target_active_sessions[quiz_id].id
                if guest_active_sessions[quiz_id].updated_at > target_active_sessions[quiz_id].updated_at
                else guest_active_sessions[quiz_id].id
                for quiz_id in set(guest_active_sessions) & set(target_active_sessions)
            ]
            QuizSession.objects.filter(id__in=to_archive).update(is_active=False, ended_at=timezone.now())

            QuizSession.objects.filter(user=guest).update(user=target_user)

            guest_root = guest.root_folder
            target_root = target_user.root_folder

            if guest_root and target_root:
                Quiz.objects.filter(folder=guest_root).update(folder=target_root)
                Folder.objects.filter(parent=guest_root).update(parent=target_root, owner=target_user)
                Folder.objects.filter(owner=guest).exclude(pk=guest_root.pk).update(owner=target_user)
                guest.root_folder = None
                guest.save(update_fields=["root_folder"])
                guest_root.delete()
            else:
                Folder.objects.filter(owner=guest).update(owner=target_user)

            guest.delete()

        return True

    except Exception as e:
        logger.exception(
            "Guest migration: failed for guest %s → user %s: %s",
            guest_id,
            target_user.id,
            e,
        )
        return False
