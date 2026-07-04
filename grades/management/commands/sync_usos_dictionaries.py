from typing import Literal, cast

import requests
from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError
from usos_api.services.courses import CourseClassTypesIndex

from grades.class_types import sync_class_types
from grades.terms import TermDescription, sync_terms

DEFAULT_USOS_BASE_URL = "https://apps.usos.pwr.edu.pl/"
Resource = Literal["all", "class-types", "terms"]


class Command(BaseCommand):
    help = "Sync public USOS dictionary data into the local database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            default=DEFAULT_USOS_BASE_URL,
            help="USOS API base URL.",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=30.0,
            help="HTTP timeout in seconds.",
        )
        parser.add_argument(
            "--resource",
            choices=["all", "class-types", "terms"],
            default="all",
            help="Which dictionary to sync.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and validate data without writing to the database.",
        )

    def handle(self, *args, **options):
        base_url = options["base_url"].rstrip("/") + "/"
        resource = cast(Resource, options["resource"])
        dry_run = options["dry_run"]

        if resource in {"all", "class-types"}:
            class_types = self._fetch_class_types(base_url, options["timeout"])
            if dry_run:
                self.stdout.write(self.style.SUCCESS(f"Fetched {len(class_types)} class types."))
            else:
                synced_count = async_to_sync(sync_class_types)(class_types)
                self.stdout.write(self.style.SUCCESS(f"Synced {synced_count} class types."))

        if resource in {"all", "terms"}:
            terms = self._fetch_terms(base_url, options["timeout"])
            if dry_run:
                self.stdout.write(self.style.SUCCESS(f"Fetched {len(terms)} terms."))
            else:
                synced_count = async_to_sync(sync_terms)(terms)
                self.stdout.write(self.style.SUCCESS(f"Synced {synced_count} terms."))

    def _fetch_class_types(self, base_url: str, timeout: float) -> CourseClassTypesIndex:
        data = self._get_json(
            f"{base_url}services/courses/classtypes_index",
            timeout=timeout,
        )
        if not isinstance(data, dict):
            raise CommandError("USOS returned invalid class type index payload.")
        return cast(CourseClassTypesIndex, data)

    def _fetch_terms(self, base_url: str, timeout: float) -> list[TermDescription]:
        data = self._get_json(
            f"{base_url}services/terms/terms_index",
            timeout=timeout,
            params={
                "active_only": "false",
            },
        )
        if not isinstance(data, list):
            raise CommandError("USOS returned invalid terms index payload.")
        return data

    def _get_json(
        self,
        url: str,
        *,
        timeout: float,
        params: dict[str, str] | None = None,
    ):
        try:
            response = requests.get(
                url,
                params={"format": "json", **(params or {})},
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise CommandError(f"Failed to fetch {url}: {exc}") from exc
