from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from ai.models import (
    AIChatConversation,
    AIFallbackGrant,
    AIUsageDailyAggregate,
    AIUsageEvent,
)

DEFAULT_USAGE_RETENTION_DAYS = 90
DEFAULT_CHAT_HISTORY_RETENTION_DAYS = 180
PRUNE_ADVISORY_LOCK_ID = 0x41495553414745

AGGREGATE_TOTAL_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "credits",
    "event_count",
    "aborted_count",
    "error_count",
)


def _upsert_aggregate_rows(rows, chunk_size=1000):
    quote = connection.ops.quote_name
    table = quote(AIUsageDailyAggregate._meta.db_table)
    model_field = AIUsageDailyAggregate._meta.get_field("model")
    key_columns = ("user_id", "date", "scope", model_field.column)
    columns = (*key_columns, *AGGREGATE_TOTAL_FIELDS)
    assignments = ", ".join(
        f"{quote(field)} = {table}.{quote(field)} + excluded.{quote(field)}" for field in AGGREGATE_TOTAL_FIELDS
    )
    sql = (
        f"INSERT INTO {table} ({', '.join(quote(column) for column in columns)}) "
        f"VALUES ({', '.join(['%s'] * len(columns))}) "
        f"ON CONFLICT ({', '.join(quote(column) for column in key_columns)}) "
        f"DO UPDATE SET {assignments}"
    )
    batch = []
    user_id_field = AIUsageDailyAggregate._meta.get_field("user").target_field
    model_id_field = model_field.target_field
    with connection.cursor() as cursor:
        for row in rows.iterator(chunk_size=chunk_size):
            batch.append(
                (
                    user_id_field.get_db_prep_value(row["user_id"], connection),
                    row["created_at__date"],
                    row["scope"],
                    model_id_field.get_db_prep_value(row["model"], connection),
                    *(row[field] or 0 for field in AGGREGATE_TOTAL_FIELDS),
                )
            )
            if len(batch) == chunk_size:
                cursor.executemany(sql, batch)
                batch.clear()
        if batch:
            cursor.executemany(sql, batch)


def _lock_prune_run():
    """Prevent overlapping PostgreSQL runs from aggregating the same events twice."""
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [PRUNE_ADVISORY_LOCK_ID])
        if not cursor.fetchone()[0]:
            raise CommandError("Another prune_ai_usage command is already running.")


class Command(BaseCommand):
    help = "Roll old AI usage events into daily aggregates and prune old chat history."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--usage-retention-days",
            type=int,
            default=DEFAULT_USAGE_RETENTION_DAYS,
            help=f"Roll up usage events older than this many days (default: {DEFAULT_USAGE_RETENTION_DAYS}).",
        )
        parser.add_argument(
            "--chat-history-retention-days",
            type=int,
            default=DEFAULT_CHAT_HISTORY_RETENTION_DAYS,
            help=f"Delete chat history older than this many days (default: {DEFAULT_CHAT_HISTORY_RETENTION_DAYS}).",
        )

    def handle(self, *args, **options):
        usage_retention_days = options["usage_retention_days"]
        chat_history_retention_days = options["chat_history_retention_days"]
        if usage_retention_days < 1 or chat_history_retention_days < 1:
            raise CommandError("Retention periods must be positive numbers of days.")
        today = timezone.localdate()
        usage_cutoff_date = today - timedelta(days=usage_retention_days)
        usage_cutoff = timezone.make_aware(
            datetime.combine(usage_cutoff_date, time.min), timezone.get_current_timezone()
        )
        old_events = AIUsageEvent.objects.filter(created_at__lt=usage_cutoff)
        rows = old_events.values("user_id", "created_at__date", "scope", "model").annotate(
            input_tokens=Sum("input_tokens"),
            output_tokens=Sum("output_tokens"),
            cache_read_tokens=Sum("cache_read_tokens"),
            cache_write_tokens=Sum("cache_write_tokens"),
            credits=Sum("credits"),
            event_count=Count("id"),
            aborted_count=Count("id", filter=Q(aborted=True)),
            error_count=Count("id", filter=~Q(error="")),
        )
        chat_cutoff = timezone.now() - timedelta(days=chat_history_retention_days)
        chat_rows = AIChatConversation.objects.filter(updated_at__lt=chat_cutoff)
        grant_rows = AIFallbackGrant.objects.filter(issued_at__lt=usage_cutoff)
        if options["dry_run"]:
            self.stdout.write(
                f"Would roll up {old_events.count()} events into {rows.count()} rows, "
                f"prune {chat_rows.count()} conversations, and prune {grant_rows.count()} fallback grants."
            )
            return
        with transaction.atomic():
            _lock_prune_run()
            _upsert_aggregate_rows(rows)
            _, deleted_events = old_events.delete()
            _, deleted_chats = chat_rows.delete()
            _, deleted_grants = grant_rows.delete()
            event_count = deleted_events.get(AIUsageEvent._meta.label, 0)
            chat_count = deleted_chats.get(AIChatConversation._meta.label, 0)
            grant_count = deleted_grants.get(AIFallbackGrant._meta.label, 0)
        self.stdout.write(
            self.style.SUCCESS(
                f"Pruned {event_count} event rows, {chat_count} chat rows, and {grant_count} fallback grants."
            )
        )
