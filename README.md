# <img src="https://github.com/Solvro/web-testownik/blob/main/public/favicon/192x192.png?raw=true" width="24"> Testownik Solvro - Backend

<div align="center">

![Python](https://img.shields.io/badge/python-%233776AB.svg?style=for-the-badge&logo=python&logoColor=white)
![Django](https://img.shields.io/badge/django-%23092E20.svg?style=for-the-badge&logo=django&logoColor=white)
![DjangoREST](https://img.shields.io/badge/DJANGO-REST-ff1709?style=for-the-badge&logo=django&logoColor=white&color=ff1709&labelColor=gray)

**Twoje narzędzie do nauki na Politechnice Wrocławskiej**

[🌐 Odwiedź aplikację](https://testownik.solvro.pl) • [🧑‍💻 Repozytorium frontend](https://github.com/Solvro/web-testownik) • [🛠️ API Swagger](https://testownik.solvro.pl/api/)

</div>

---

## 📖 O projekcie

**Testownik Solvro** to platforma edukacyjna stworzona przez [KN Solvro](https://github.com/Solvro) dla studentów Politechniki Wrocławskiej. Aplikacja umożliwia tworzenie, rozwiązywanie i udostępnianie quizów, pomagając w przygotowaniu do sesji egzaminacyjnej.

---

## 🚀 Uruchomienie lokalne

### Wymagania

- Python **3.10+**
- pip

### Instalacja

1. **Sklonuj repozytorium**

   ```bash
   git clone https://github.com/Solvro/backend-testownik.git
   cd backend-testownik
   ```

2. **Utwórz i aktywuj środowisko wirtualne**

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Linux / macOS
   .venv\Scripts\activate           # Windows
   ```

3. **Zainstaluj zależności**

   ```bash
   pip install -r requirements.txt
   ```

4. **Skopiuj plik środowiskowy**

   ```
   cp .env.example .env
   ```

5. **Wykonaj migracje bazy danych**

   ```bash
   python manage.py migrate
   ```

6. **(Opcjonalnie) Stwórz konto administratora**

   ```bash
   python manage.py createsuperuser
   ```

7. **Uruchom serwer deweloperski**

   ```bash
   python manage.py runserver
   ```

Po uruchomieniu API będzie dostępne pod:  
[http://localhost:8000/](http://localhost:8000/)

---

## 📜 Najważniejsze komendy

| Komenda                            | Opis                          |
| ---------------------------------- | ----------------------------- |
| `python manage.py runserver`       | Uruchamia serwer deweloperski |
| `python manage.py migrate`         | Wykonuje migracje bazy danych |
| `python manage.py createsuperuser` | Tworzy konto administratora   |
| `pip install -r requirements.txt`  | Instaluje zależności          |

---

## 🛠️ Stack technologiczny

- **Język:** Python 3
- **Framework:** Django + Django REST Framework
- **Baza danych:** PostgreSQL (prod) / SQLite (dev)
- **Uwierzytelnianie:** JWT (JSON Web Tokens)
- **Integracja z USOS:** [`usos-api`](https://pypi.org/project/usos-api/)
- **Dokumentacja API:** DRF Spectacular • Swagger UI

---

## 🤝 Kontrybucja

Chcesz pomóc w rozwoju Testownika? Let's go!

1. Sforkuj repozytorium (tylko jeśli jeszcze nie jesteś w teamie testownika)
2. Stwórz branch dla swojej funkcji (`git checkout -b feat/amazing-feature`)
3. Commituj zmiany (`git commit -m 'feat: add amazing feature'`)
4. Wypchnij branch (`git push origin feature/amazing-feature`)
5. Otwórz Pull Request

Aby było nam wszystkim łatwiej stosuj się do tych zasad przy tworzeniu branchy oraz commitów.

### 🪾 Nazewnictwo branchy

Każdy branch powinien zawierać **prefiks określający typ zmiany** oraz **numer GitHub Issue**.

**Format**

```
<prefix>/<issue>-short-description
```

**Dostępne prefiksy**

- `feat/` - nowe funkcje
- `fix/` - poprawki błędów
- `hotfix/` - krytyczne poprawki produkcyjne
- `design/` - zmiany UI/UX
- `refactor/` - poprawa kodu bez zmiany działania
- `test/` - testy
- `docs/` - dokumentacja

**Przykłady**

```
feat/123-add-usos-integration
fix/87-token-refresh-bug
refactor/210-cleanup-serializers
```


### 🧹 Pre-commit i jakość kodu

W projekcie używamy [pre-commit](https://pre-commit.com/) oraz [ruff](https://docs.astral.sh/ruff/) do automatycznego formatowania i lintowania kodu przy każdym `git commit`.

**Instalacja narzędzi deweloperskich**

   ```bash
      pip install -r requirements-dev.txt
   ```

**Instalacja hooków pre-commit**

   ```bash
      pre-commit install
   ```

**Ręczne uruchomienie wszystkich hooków**

   ```bash
      pre-commit run --all-files
   ```


Po instalacji hooków, przy każdym `git commit` automatycznie uruchomią się:

- `ruff` – linting i sortowanie importów

- `ruff-format` – formatowanie kodu


### ✍️ Format commitów

Stosujemy standard [**Conventional Commits**](https://www.conventionalcommits.org/en/v1.0.0/), aby się móc później łatwiej połapać.

**Format**

```
<type>(opcjonalny scope): opis w czasie teraźniejszym
```

**Typy commitów**

- `feat:` - nowa funkcjonalność
- `fix:` - naprawa błędu
- `docs:` - dokumentacja
- `refactor:` - poprawa struktury kodu
- `test:` - testy
- `chore:` - zmiany w konfiguracji, dependency itp.

**Przykłady**

```bash
   feat(auth): add USOS SSO login
   fix(quizzes): correct question ordering
   docs: update README with backend setup
```
---

## 🐞 Zgłaszanie problemów, pomysłów i pytań

Niepewny czego dotyczy temat? Zgłoś go najpierw na [frontendzie](https://github.com/Solvro/web-testownik/issues/new).

Jeśli jesteś dość pewien, że sprawa dotyczy **wyłącznie backendu**
(API, baza danych, logika serwera), wtedy wrzuć zgłoszenie na [backendzie](https://github.com/Solvro/backend-testownik/issues/new).

---

## 📬 Kontakt

- **Email:** [testownik@solvro.pl](mailto:testownik@solvro.pl)
- **Organizacja:** [KN Solvro](https://github.com/Solvro)
- **Strona:** [testownik.solvro.pl](https://testownik.solvro.pl)

---

<div align="center">

Stworzone z ❤️ przez [KN Solvro](https://github.com/Solvro) dla studentów Politechniki Wrocławskiej

⭐ Jeśli projekt Ci się podoba, zostaw gwiazdkę!

</div>
