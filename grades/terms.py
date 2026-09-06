from datetime import date
from typing import TypedDict

from users.models import Term


class LangDictData(TypedDict, total=False):
    pl: str | None
    en: str | None


class TermDescription(TypedDict):
    id: str
    order_key: int
    name: LangDictData
    start_date: str
    end_date: str
    finish_date: str
    is_active: bool


def _lang_text(value: LangDictData | None, lang: str = "pl") -> str | None:
    if value is None:
        return None
    return value.get(lang) or value.get("en") or value.get("pl")


def _date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


async def sync_terms(terms: list[TermDescription]) -> int:
    for term in terms:
        await Term.objects.aupdate_or_create(
            id=term["id"],
            defaults={
                "name": _lang_text(term.get("name")),
                "start_date": _date(term.get("start_date")),
                "end_date": _date(term.get("end_date")),
                "finish_date": _date(term.get("finish_date")),
            },
        )
    return len(terms)


async def get_terms(term_ids: list[str]) -> list[Term]:
    return [term async for term in Term.objects.filter(id__in=term_ids).aiterator()]
