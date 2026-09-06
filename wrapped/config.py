"""Configuration + term helpers for Testownik Wrapped.

The season window and labels are derived from `users.Term` (never hardcoded).

Whether Wrapped is live is controlled by the `WRAPPED_ENABLED` constance flag,
not a date, so it can be toggled without a deploy.
"""

from __future__ import annotations

import re
from datetime import date

from users.models import Term

# --- Scoring ----------------------------------------------------------------

# Composite "wytrwałość" score weights. Must sum to 1.0.
COMPOSITE_WEIGHTS = {
    "study": 0.5,
    "answers": 0.3,
    "active_days": 0.2,
}

TOP_QUIZZES_LIMIT = 5

# --- Terms ------------------------------------------------------------------

# Real academic term ids look like "2024/25-Z", "2024/25-L" or "2024/25".
# Bookkeeping terms (WINDYKACJA, BO-JSOS, …) don't match and are ignored.
REAL_TERM_ID = re.compile(r"^\d{4}/\d{2}(-[ZL])?$")

_PL_MONTHS = [
    "sty",
    "lut",
    "mar",
    "kwi",
    "maj",
    "cze",
    "lip",
    "sie",
    "wrz",
    "paź",
    "lis",
    "gru",
]


def is_real_term(term_id: str) -> bool:
    return bool(REAL_TERM_ID.match(term_id or ""))


def real_terms():
    """All eligible terms (real id, has start + finish), newest first."""
    terms = [t for t in Term.objects.all() if is_real_term(t.id) and t.start_date and t.finish_date]
    return sorted(terms, key=lambda t: t.finish_date, reverse=True)


def _is_semester(term: Term) -> bool:
    return "-" in term.id  # e.g. 2024/25-Z vs the whole-year 2024/25


def select_term(term_id: str | None = None) -> Term | None:
    """Resolve the term to generate for.

    With `term_id`, returns that term (if real). Otherwise the current semester
    (today within [start, finish]), preferring semester terms over the
    whole-year term, and falling back to the most recent semester.
    """
    terms = real_terms()
    if term_id is not None:
        return next((t for t in terms if t.id == term_id), None)

    today = date.today()
    current = [t for t in terms if t.start_date <= today <= t.finish_date]
    semesters_current = [t for t in current if _is_semester(t)]
    pool = semesters_current or current
    if pool:
        return max(pool, key=lambda t: t.finish_date)

    semesters = [t for t in terms if _is_semester(t)]
    return (semesters or terms)[0] if terms else None


def year_label(term: Term) -> str:
    """'2024/25-Z' → '24/25'."""
    base = term.id.split("-")[0]
    if "/" in base:
        left, right = base.split("/", 1)
        return f"{left[-2:]}/{right[-2:]}"
    return term.id


def _pl_date(value: date) -> str:
    return f"{value.day} {_PL_MONTHS[value.month - 1]}"


def date_range_label(term: Term, upper_bound: date | None = None) -> str:
    """'1 paź — 28 lut' from the term's start date to the visible end date."""
    end_date = term.finish_date
    if upper_bound is not None:
        end_date = min(term.finish_date, upper_bound)
        end_date = max(term.start_date, end_date)
    return f"{_pl_date(term.start_date)} — {_pl_date(end_date)}"


def season_block(term: Term, upper_bound: date | None = None) -> dict[str, str]:
    """The `season` block of the payload, derived from the term."""
    return {
        "label": term.name or term.id,
        "date_range": date_range_label(term, upper_bound),
        "year_label": year_label(term),
    }
