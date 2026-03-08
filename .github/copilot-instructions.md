# Copilot Instructions (backend-testownik)

## Project overview
Django 6 + DRF backend for [Testownik](https://testownik.solvro.pl), a quiz platform for Wrocław University of Technology students. Python, PostgreSQL (prod) / SQLite (dev).

## Architecture

### Apps and their roles
| App                    | Purpose                                                                                                                                |
|------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| `testownik_core/`      | Project root — settings, root URL config, email utility, management commands                                                           |
| `users/`               | Custom `User` model (email-based auth), OAuth (Solvro Keycloak + USOS), OTP/magic-link login, JWT cookie handling, study groups, terms |
| `quizzes/`             | Core domain — Quiz/Question/Answer CRUD, quiz sessions & progress tracking, sharing, folders, search, copy, reporting                  |
| `alerts/`              | Admin-managed in-app alert banners                                                                                                     |
| `maintenance/`         | Maintenance-mode middleware via `django-constance`                                                                                     |
| `uploads/`             | Image uploads (S3 or local storage)                                                                                                    |
| `feedback/`, `grades/` | Stub apps — without models, only data fetching                                                                                         |

### Key patterns
- **UUID primary keys** on all models: `id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`.
- **Nested serializer writes** — `QuizSerializer` handles nested Question → Answer creation/updates in `@transaction.atomic` blocks using `_sync_questions` / `_batch_sync_answers` diffing.
- **Read/write field split** — Use `quiz` (read-only nested) + `quiz_id` (write-only PK) pattern. See `SharedQuizSerializer` for reference.
- **Multiple serializers per viewset** — Override `get_serializer_class()` to return different serializers per action (e.g., `QuizMetaDataSerializer` for list, `QuizSerializer` for detail).
- **Service layer** — Business logic in `quizzes/services/` (small focused modules). Background tasks use Django's `django.tasks` (`@task()` decorator, enqueued via `.enqueue()` with `transaction.on_commit()`).
- **Throttling** — Custom throttle classes for some endpoints in `quizzes/throttling.py` (e.g., `CopyQuizThrottle` at `5/m`).

### Authentication (3 flows)
1. **Solvro OAuth/OIDC** — `authlib` + Keycloak (`auth.solvro.pl`)
2. **USOS OAuth 1.0** — `usos-api` library, syncs student data & study groups
3. **Email OTP/magic link** — 6-digit code + link via `users/utils.py`

### Authorization
**JWT cookies** — returned in cookies after login`access_token` (JS-readable) + `refresh_token` (httpOnly), set via `users/auth_cookies.py`, provided via headers in DRF views (`request.auth`).

### Permissions (`quizzes/permissions.py`)
- `IsQuizReadable` — Visibility-based (private/shared/unlisted/public) with anonymous support
- `IsQuizMaintainer` — Owner-only for destructive ops
- `IsQuizMaintainerOrCollaborator` — Owner + collaborators with `allow_edit`
- `IsInternalApiRequest` — Server-to-server via `Api-Key` header (Next.js SSR)  
...

## Developer workflow

### Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate && python manage.py runserver
```

### Tests & linting
```bash
python manage.py test                  # all tests
ruff check .                           # lint
ruff format --check .                  # format check
pre-commit run --all-files             # run all pre-commit hooks
```
CI runs both on Python 3 (`.github/workflows/tests.yml` and `lint.yml`).

### Ruff config (`pyproject.toml`)
- Line length: **120**, target: `py313`
- Rules: `E`, `F`, `DJ`, `UP`, `SIM`, `I` (isort)
- Migrations excluded from lint/format

## Coding conventions
- Follow existing module layout: `models.py`, `views.py`, `serializers.py`, `urls.py`, `permissions.py`, `services/`, `tests/`.
- Use `ModelViewSet` for standard CRUD; add `@action` decorators for custom endpoints.
- Use `APIView` or `generics.*` for standalone endpoints.
- Decorate views with `@extend_schema` for OpenAPI docs (drf-spectacular).
- Register viewsets with `DefaultRouter` in each app's `urls.py`; include under `/api/` in `testownik_core/urls.py`.
- Use `testownik_core/emails.py` → `send_email()` for all outgoing email.
- Tests use `rest_framework.test.APITestCase`, `self.client.force_authenticate()`, and `reverse()` for URL resolution.
- Do not add new dependencies unless clearly needed.

## Commits & branches

**Conventional Commits** (enforced by commitlint):
```
<type>(optional scope): present-tense description
```
Allowed types: `feat`, `fix`, `refactor`, `chore`, `docs`, `ci`, `test`, `build`, `release`.

**Branch naming:**
```
<prefix>/<issue>-short-description
```
Prefixes: `feat/`, `fix/`, `hotfix/`, `design/`, `refactor/`, `test/`, `docs/`.
Example: `feat/123-add-usos-integration`
