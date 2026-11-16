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
        with transaction.atomic():
            # Serialize competing upgrades before moving any ownership or folders.
            guest = User.objects.select_for_update().get(id=guest_id)
            if guest.account_type != AccountType.GUEST or guest.id == target_user.id:
                logger.warning("Guest migration: invalid source account %s", guest_id)
                return False

            from quizzes.models import Folder, FolderType, Quiz, QuizSession

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
                protected_folder_defaults = {
                    FolderType.ARCHIVE: Folder.DEFAULT_ARCHIVE_NAME,
                    FolderType.TRASH: Folder.DEFAULT_TRASH_NAME,
                }

                for folder_type, folder_name in protected_folder_defaults.items():
                    target_folder, _ = Folder.objects.get_or_create(
                        owner=target_user,
                        folder_type=folder_type,
                        defaults={"name": folder_name, "parent": target_root},
                    )
                    guest_folder = Folder.objects.filter(owner=guest, folder_type=folder_type).first()
                    if guest_folder:
                        Quiz.objects.filter(folder=guest_folder).update(folder=target_folder)
                        guest_folder.folder_type = FolderType.REGULAR
                        guest_folder.delete()

                Quiz.objects.filter(folder=guest_root).update(folder=target_root)
                Folder.objects.filter(parent=guest_root).update(parent=target_root, owner=target_user)
                Folder.objects.filter(owner=guest).exclude(pk=guest_root.pk).update(owner=target_user)
                guest.root_folder = None
                guest.save(update_fields=["root_folder"])
                guest_root.delete()
            else:
                Folder.objects.filter(owner=guest).update(owner=target_user)

            # Pending guest uploads can be referenced after the authenticated
            # upgrade as well as by quizzes already transferred above.
            from uploads.models import UploadedImage

            UploadedImage.objects.filter(uploaded_by=guest).update(uploaded_by=target_user)
            guest.delete()

        return True

    except (User.DoesNotExist, ValidationError, ValueError):
        logger.warning("Guest migration: guest user %s not found", guest_id)
        return False
    except Exception as e:
        logger.exception(
            "Guest migration: failed for guest %s → user %s: %s",
            guest_id,
            target_user.id,
            e,
        )
        return False


def delete_account(user: User) -> None:
    """Delete an account and everything it owns, within the caller's transaction.

    Quizzes block deleting their folder, so the account's own quizzes go first, and
    anyone else's quiz filed in one of its folders moves to its creator's root folder.
    """
    from quizzes.models import Quiz, QuizSession, SharedQuiz

    Quiz.objects.filter(creator=user).delete()
    for quiz in Quiz.objects.filter(folder__owner=user).select_related("creator__root_folder"):
        quiz.folder = quiz.creator.root_folder
        quiz.save(update_fields=["folder"])
    QuizSession.objects.filter(user=user).delete()
    SharedQuiz.objects.filter(user=user).delete()
    user.delete()
