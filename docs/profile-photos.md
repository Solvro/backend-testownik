# Profile photos

Authenticated, non-guest users can POST a multipart `photo` file to
`/api/user/photo/`, or DELETE the same endpoint to restore their account photo.
Both return the complete current-user profile, including `photo` (nullable URL)
and `has_custom_photo`. Refresh the JWT after a change to update embedded avatars.
PATCH `/api/user/` no longer accepts photo URLs. Upload limits and supported
formats are shared with the uploads app: JPEG, PNG, GIF, WebP, AVIF, up to 10 MiB.

## Deploy and run the worker

Install requirements and run `python manage.py migrate` before starting the web
service and a separate, supervised worker process using the same release:

```sh
python manage.py db_worker --backend images --queue-name images --no-reload
```

The worker needs the same database, `BACKEND_URL`, image-source allowlist, and
storage configuration as the web service. With filesystem storage, mount the same
media directory into both processes. Run it under the deployment platform's worker
service/process supervisor with automatic restart. PostgreSQL is recommended for
multiple workers; use one worker for SQLite development. The existing default
email-task backend is unchanged.

USOS and Solvro login only enqueue after the user transaction commits. Photo
downloads and processing run in the worker. Existing photos younger than 24 hours
skip downloading. Failed downloads are recorded as FAILED tasks; the next login
can enqueue a new attempt. A queue failure is logged without preventing login.
Monitor READY task age and FAILED counts in the Django Tasks DB admin. If the
worker is stopped, logins continue and work remains queued until it resumes.

Prune completed tasks periodically (arguments include source URLs and should not
be retained indefinitely):

```sh
python manage.py prune_db_task_results --backend images --queue-name images --min-age-days 7
```

## Legacy custom photos

Migrations perform no network I/O. The legacy `overriden_photo_url` column is kept
as a backfill source; existing custom photos remain visible until converted.
After deployment, run in batches outside the migration/release critical path:

```sh
python manage.py backfill_user_photos --dry-run
python manage.py backfill_user_photos --batch-size 100 --limit 1000
```

Both worker and backfill downloads use the same bounded urllib3 transport. Only
allowlisted hosts are fetched; every resolved address must be public, and the
connection is pinned to one validated address while preserving the original TLS
hostname and Host header. Redirects and compressed HTTP responses are rejected,
and downloads are capped at 10 MiB. Legacy DiceBear SVG choices use the provider's PNG endpoint.
Successful conversions clear the legacy URL; failures retain it for later review.
Do not remove the legacy column until all remaining URLs have been accounted for.
Uploading or resetting a photo clears the URL and wins over concurrent backfill.

Replaced and reset image files are retained until `cleanup_orphans`; that command
preserves images referenced by either profile-photo FK as well as quiz content.
