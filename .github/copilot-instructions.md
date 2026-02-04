# Copilot Instructions (backend-testownik)

## Kontekst projektu
- Stack: Python 3 + Django + Django REST Framework.
- Preferuj istniejące aplikacje i wzorce z katalogów w repozytorium.

## Zasady pracy z kodem
- Trzymaj się istniejącej struktury modułów i stylu kodu.
- Nie dodawaj nowych zależności bez wyraźnej potrzeby.
- Przy zmianach API zachowuj kompatybilność i stosuj istniejące serializery, widoki i testy.

## Wymagania `@solvro/config` (commitlint)
Stosujemy **Conventional Commits**. Format:

```
<type>(opcjonalny scope): opis w czasie teraźniejszym
```

Dozwolone typy commitów:
- `feat`
- `fix`
- `refactor`
- `chore`
- `docs`
- `ci`
- `test`
- `build`
- `release`

Inne typy (np. `perf`, `revert`, `style`) nie są akceptowane w tym projekcie.

## Opis commitów (styl)
- Opis krótki, po angielsku, opisujący czego dotyczy zmiana.
- Używaj czasu teraźniejszego (np. `add`, nie `added`).
- Pierwsza linia powinna być zwięzła i nie wykraczać poza widoczne na GitHubie miejsce.
- Dopuszczalne są zakresy, np. `feat(blog): code snippets`.

## Nazewnictwo commitów (z handbooka Solvro)
- Proponowany format: `type: short description` (lub `type(scope): short description`).
- Przedrostki z handbooka: `feat`, `fix`, `refactor`, `chore`, `docs`, `ci`, `test`.
- W tym repo obowiązują dodatkowo `build` i `release` (wynika z `@solvro/config`).
- Czasami spotkasz inne przedrostki, ale w tym repo są blokowane przez commitlint.
- Polecana specyfikacja: https://www.conventionalcommits.org/en/v1.0.0/
- Przykłady krótkiego opisu: `login view`, `shopping list`, `auth service`, `offline message widget`.

## Nazewnictwo branchy (z README)
Format:

```
<prefix>/<issue>-short-description
```

Dostępne prefiksy:
- `feat/`
- `fix/`
- `hotfix/`
- `design/`
- `refactor/`
- `test/`
- `docs/`

Przykłady:

```
feat/123-add-usos-integration
fix/87-token-refresh-bug
refactor/210-cleanup-serializers
```

## Nazewnictwo repozytoriów (handbook Solvro)
- Format: `typ-projektu-nazwa-projektu-suffixy` w pełnym lower-kebab-case.
- Prefiksy typów: `backend-`, `web-`, `lib-web-`, `ml-`, `mobile-`, `script-`.
- Gdy repo zawiera frontend i backend, preferuj rozdział, a jeśli to niemożliwe — wybierz prefiks `web-`.
