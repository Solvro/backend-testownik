"""Generate/refresh Wrapped reports for a term.

    python manage.py generate_wrapped                 # current term, everyone + global
    python manage.py generate_wrapped --term 2024/25-Z
    python manage.py generate_wrapped --user <uuid>   # one user, no global
    python manage.py generate_wrapped --global         # only the platform report
    python manage.py generate_wrapped --dry-run

The endpoint then just reads `WrappedReport`, so it does no live aggregation.
"""

import logging
import uuid

from django.core.management.base import BaseCommand, CommandError

from wrapped import config
from wrapped.aggregation import (
    build_global_report,
    build_user_report,
    compute_ranking,
    term_window,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Precompute Wrapped reports for a term (per-user + a global one)."

    def add_arguments(self, parser):
        parser.add_argument("--term", default=None, help="Term id (default: current/latest real term).")
        parser.add_argument("--user", default=None, help="Only (re)generate for this user id (UUID).")
        parser.add_argument(
            "--global",
            action="store_true",
            dest="only_global",
            help="Only (re)generate the platform-wide report.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Compute but do not write.")

    def handle(self, *args, **options):
        term = config.select_term(options["term"])
        if term is None:
            raise CommandError("No eligible term found (need a real term with dates).")
        self.stdout.write(f"Term {term.id} · {term.name}")

        start, end = term_window(term)

        # Global report (unless a single user was requested).
        if not options["user"]:
            if options["dry_run"]:
                self.stdout.write("Would generate the global report.")
            else:
                ok = build_global_report(term)
                self.stdout.write(
                    self.style.SUCCESS("Global report generated.") if ok else "No global activity — skipped."
                )
            if options["only_global"]:
                return

        self.stdout.write("Ranking users…")
        ranking = compute_ranking(start, end)
        user_ids = list(ranking)
        if options["user"] is not None:
            try:
                target = uuid.UUID(options["user"])
            except ValueError as exc:
                raise CommandError(f"Invalid user id: {options['user']}") from exc
            user_ids = [target] if target in ranking else []

        self.stdout.write(f"{len(user_ids)} eligible user(s).")
        created = skipped = failed = 0
        for user_id in user_ids:
            if options["dry_run"]:
                continue
            try:
                if build_user_report(user_id, term, ranking[user_id]):
                    created += 1
                else:
                    skipped += 1
            except Exception:  # noqa: BLE001 - one bad user shouldn't stop the batch
                failed += 1
                logger.exception("Failed to generate Wrapped for user %s", user_id)

        verb = "Would write" if options["dry_run"] else "Wrote"
        self.stdout.write(self.style.SUCCESS(f"{verb} {created}, skipped {skipped} (no activity), failed {failed}."))
