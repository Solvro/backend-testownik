from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from uploads.models import UploadedImage


class Command(BaseCommand):
    """Management command to clean up orphaned uploaded images."""

    help = (
        "Deletes uploaded images that are not referenced by any Question or Answer "
        "and are older than the specified threshold (default: 24 hours)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=24,
            help="Delete images older than X hours (default: 24)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed information about each image",
        )

    def handle(self, *args, **options):
        hours = options["hours"]
        dry_run = options["dry_run"]
        verbose = options["verbose"]
        cutoff = timezone.now() - timedelta(hours=hours)

        # Statistics
        total_images = UploadedImage.objects.count()

        # Find orphaned images older than cutoff
        orphans = UploadedImage.objects.filter(
            uploaded_at__lt=cutoff, questions__isnull=True, answers__isnull=True
        ).distinct()

        orphan_count = orphans.count()
        total_size = orphans.aggregate(total=Sum("file_size"))["total"] or 0

        self.stdout.write("\nImage Statistics:")
        self.stdout.write(f"   Total images: {total_images}")
        self.stdout.write(f"   Orphaned (>{hours}h old): {orphan_count}")
        self.stdout.write(f"   Space to reclaim: {total_size / (1024 * 1024):.2f} MB\n")

        if orphan_count == 0:
            self.stdout.write(self.style.SUCCESS("No orphaned images found."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No files will be deleted\n"))

        if verbose or dry_run:
            for img in orphans[:50]:
                size_kb = (img.file_size or 0) / 1024
                age_hours = (timezone.now() - img.uploaded_at).total_seconds() / 3600
                self.stdout.write(
                    f"  {'[DRY RUN] ' if dry_run else ''} {img.id} | "
                    f"{img.original_filename[:40]:<40} | "
                    f"{size_kb:>8.1f} KB | "
                    f"{age_hours:>6.1f}h old"
                )
            if orphan_count > 50:
                self.stdout.write(f"  ... and {orphan_count - 50} more")

        if dry_run:
            self.stdout.write(f"\nWould delete {orphan_count} images ({total_size / (1024 * 1024):.2f} MB)")
            return

        self.stdout.write(f"\nDeleting {orphan_count} orphaned images...")

        deleted_count = 0
        failed_count = 0

        for img in orphans:
            try:
                img.delete()
                deleted_count += 1
            except Exception as e:
                failed_count += 1
                self.stderr.write(self.style.ERROR(f"Failed to delete {img.id}: {e}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSuccessfully deleted {deleted_count} orphaned images "
                f"({total_size / (1024 * 1024):.2f} MB reclaimed)"
            )
        )
        if failed_count:
            self.stdout.write(self.style.WARNING(f"Failed to delete {failed_count} images"))
