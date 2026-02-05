# Copilot Instructions (backend-testownik)

## Project context
- Stack: Python 3 + Django + Django REST Framework.
- Backend for Testownik app.
- Prefer existing apps and patterns from the repository folders.

## Coding rules
- Stick to the existing module structure and code style.
- Do not add new dependencies unless clearly needed.
- When changing the API, aim for compatibility and use existing serializers, views, and tests; if bigger changes are required, explain the decision clearly.

## Rrequirements (commitlint)
We use **Conventional Commits**. Format:

```
<type>(optional scope): present-tense description
```

Allowed commit types:
- `feat`
- `fix`
- `refactor`
- `chore`
- `docs`
- `ci`
- `test`
- `build`
- `release`

## Commit messages (style)
- Short, in English, describing what the change is about.
- Use present tense (e.g., `add`, not `added`).
- Keep the first line concise so it fits the GitHub view.
- Scopes are allowed, e.g., `feat(blog): code snippets`.

## Commit naming (Solvro handbook)
- Recommended format: `type: short description` (or `type(scope): short description`).
- Handbook prefixes: `feat`, `fix`, `refactor`, `chore`, `docs`, `ci`, `test`.
- This repo additionally allows `build` and `release` (from `@solvro/config`).
- You may see other prefixes, but commitlint blocks them here.
- Recommended spec: https://www.conventionalcommits.org/en/v1.0.0/
- Examples of short descriptions: `login view`, `shopping list`, `auth service`, `offline message widget`.

## Branch naming (from README)
Format:

```
<prefix>/<issue>-short-description
```

Available prefixes:
- `feat/`
- `fix/`
- `hotfix/`
- `design/`
- `refactor/`
- `test/`
- `docs/`

Examples:

```
feat/123-add-usos-integration
fix/87-token-refresh-bug
refactor/210-cleanup-serializers
```
