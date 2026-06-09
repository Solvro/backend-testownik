import logging
import time
from urllib.parse import urlparse

import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from uploads.models import UploadedImage
from uploads.utils import process_uploaded_image, validate_image_source_url
from users.models import User

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024
DEFAULT_BATCH_SIZE = 100
DEFAULT_TIMEOUT = 5


class Command(BaseCommand):
    help = (
        "Backfill custom_photo_image from the legacy overriden_photo_url field. "
        "Downloads each photo from a third-party host, so it is meant to be run "
        "out-of-band (not during `migrate`). Idempotent and batched."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Number of users to process per batch (default: {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of users to process this run (default: no limit).",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=DEFAULT_TIMEOUT,
            help=f"Per-request HTTP timeout in seconds (default: {DEFAULT_TIMEOUT}).",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.0,
            help="Seconds to sleep between batches to ease load on the source host (default: 0).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be processed without downloading or writing anything.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        limit = options["limit"]
        timeout = options["timeout"]
        sleep_between = options["sleep"]
        dry_run = options["dry_run"]

        if batch_size <= 0:
            raise CommandError("--batch-size must be a positive integer.")

        # Idempotent: only users that still have a source URL and no custom photo yet.
        base_qs = (
            User.objects.filter(overriden_photo_url__isnull=False)
            .exclude(overriden_photo_url="")
            .filter(custom_photo_image__isnull=True)
            .order_by("id")
        )

        total_candidates = base_qs.count()
        to_process = min(total_candidates, limit) if limit is not None else total_candidates

        self.stdout.write(
            f"{total_candidates} candidate user(s); processing up to {to_process} "
            f"(batch size {batch_size}){' [dry-run]' if dry_run else ''}."
        )

        processed = succeeded = skipped = failed = 0

        for user in base_qs.iterator(chunk_size=batch_size):
            if limit is not None and processed >= limit:
                break
            processed += 1

            result = self._process_user(user, timeout=timeout, dry_run=dry_run)
            if result == "ok":
                succeeded += 1
            elif result == "skip":
                skipped += 1
            else:
                failed += 1

            if sleep_between and processed % batch_size == 0:
                time.sleep(sleep_between)

        self.stdout.write(
            self.style.SUCCESS(f"Done. processed={processed} succeeded={succeeded} skipped={skipped} failed={failed}")
        )
        if not dry_run and (base_qs.count() == 0):
            self.stdout.write(
                self.style.SUCCESS(
                    "No remaining candidates. Safe to drop `overriden_photo_url` in a contract migration."
                )
            )

    def _process_user(self, user, *, timeout: float, dry_run: bool) -> str:
        url = user.overriden_photo_url
        try:
            validate_image_source_url(url)
        except Exception:
            logger.warning("Skipping invalid photo URL for user %s: %s", user.id, urlparse(url).hostname)
            return "skip"

        if dry_run:
            self.stdout.write(f"  would process user {user.id} ({urlparse(url).hostname})")
            return "ok"

        try:
            raw_content, content_type = self._download(url, timeout)
            img = self._save_image(user, url, raw_content, content_type)
            user.custom_photo_image_id = img.id
            user.save(update_fields=["custom_photo_image"])
            return "ok"
        except Exception:
            logger.warning("Failed to backfill custom photo for user %s (%s)", user.id, urlparse(url).hostname)
            return "fail"

    def _download(self, url: str, timeout: float) -> tuple[bytes, str]:
        with requests.get(url, timeout=timeout, stream=True, allow_redirects=False) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "image/jpeg")

            content_length = response.headers.get("Content-Length")
            if content_length and content_length.isdigit() and int(content_length) > MAX_FILE_SIZE:
                raise ValueError("Custom photo exceeds max file size")

            content = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                content.extend(chunk)
                if len(content) > MAX_FILE_SIZE:
                    raise ValueError("Custom photo exceeds max file size")

            return bytes(content), content_type

    def _save_image(self, user, url: str, raw_content: bytes, content_type: str) -> UploadedImage:
        file_name = url.split("/")[-1] or "custom_photo.jpg"
        if not file_name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            file_name += ".jpg"

        uploaded_file = SimpleUploadedFile(name=file_name, content=raw_content, content_type=content_type)
        processed_file, width, height, out_content_type = process_uploaded_image(uploaded_file)

        return UploadedImage.objects.create(
            image=processed_file,
            original_filename=file_name,
            content_type=out_content_type,
            file_size=processed_file.size,
            width=width,
            height=height,
            uploaded_by_id=user.id,
        )
