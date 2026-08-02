import argparse
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError, DjangoHelpFormatter
from django.db import transaction
from django.db.models import Count, F, Max
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from quizzes.models import Folder, Quiz, QuizSession
from users.models import AccountType, User


class CommandHelpFormatter(DjangoHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


class Command(BaseCommand):
    help = """Deletes guest users inactive for longer than the configured threshold.

Examples:
  Preview accounts and related data eligible for cleanup:
    python manage.py cleanup_guest_users --days 30 --dry-run --verbose

  Delete accounts inactive for more than 30 days (for example, from cron):
    python manage.py cleanup_guest_users --days 30
"""

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Delete guest users inactive for more than N days (default: 30)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed information about each inactive guest",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]
        verbose = options["verbose"]

        if days < 0:
            raise CommandError("--days must be zero or greater")

        cutoff = timezone.now() - timedelta(days=days)
        total_guests = User.objects.filter(account_type=AccountType.GUEST).count()
        inactive_guests = (
            User.objects.filter(account_type=AccountType.GUEST)
            .annotate(
                last_session=Max("quiz_sessions__updated_at"),
                last_quiz=Max("created_quizzes__updated_at"),
            )
            .annotate(
                last_activity=Greatest(
                    Coalesce("last_session", F("updated_at")),
                    Coalesce("last_quiz", F("updated_at")),
                    F("updated_at"),
                )
            )
            .filter(last_activity__lt=cutoff)
            .order_by("last_activity")
        )

        inactive_count = inactive_guests.count()
        self.stdout.write("Guest user statistics:")
        self.stdout.write(f"  Total guests: {total_guests}")
        self.stdout.write(f"  Inactive (>{days} days): {inactive_count}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN - No users will be deleted"))

        candidate_ids = list(inactive_guests.values_list("id", flat=True))
        eligible_count = 0
        deleted_count = 0
        failed_count = 0

        for candidate_id in candidate_ids:
            try:
                with transaction.atomic():
                    guest = (
                        User.objects.select_for_update().filter(id=candidate_id, account_type=AccountType.GUEST).first()
                    )
                    if guest is None:
                        continue

                    session_stats = QuizSession.objects.filter(user=guest).aggregate(
                        count=Count("id"),
                        last_activity=Max("updated_at"),
                    )
                    quiz_stats = Quiz.objects.filter(creator=guest).aggregate(
                        count=Count("id"),
                        last_activity=Max("updated_at"),
                    )
                    last_activity = max(
                        activity
                        for activity in (
                            guest.updated_at,
                            session_stats["last_activity"],
                            quiz_stats["last_activity"],
                        )
                        if activity is not None
                    )

                    # Activity may have happened after the initial candidate query.
                    if last_activity >= cutoff:
                        continue

                    eligible_count += 1
                    if verbose or dry_run:
                        prefix = "[DRY RUN] " if dry_run else ""
                        self.stdout.write(
                            f"  {prefix}{guest.id} | last activity: "
                            f"{last_activity.isoformat()} | "
                            f"quizzes: {quiz_stats['count']} | "
                            f"sessions: {session_stats['count']}"
                        )

                    if dry_run:
                        continue

                    QuizSession.objects.filter(user=guest).delete()
                    Quiz.objects.filter(creator=guest).delete()

                    guest.root_folder = None
                    guest.save(update_fields=["root_folder"])
                    Folder.objects.filter(owner=guest).delete()
                    guest.delete()
                    deleted_count += 1
            except Exception as exc:
                failed_count += 1
                self.stderr.write(self.style.ERROR(f"Failed to delete guest {candidate_id}: {exc}"))

        if dry_run:
            self.stdout.write(f"\nWould delete {eligible_count} guest users.")
        else:
            self.stdout.write(self.style.SUCCESS(f"\nDeleted {deleted_count} guest users."))
        self.stdout.write(f"Failed: {failed_count}")
