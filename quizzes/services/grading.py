"""Shared server grading; keep the JSON vectors in sync with the client."""

import re
import unicodedata

from quizzes.models import OpenMatching, QuestionType


class GradingError(ValueError):
    pass


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip().lower()


def simplify(text: str) -> str:
    text = unicodedata.normalize("NFKD", normalize(text).replace("ł", "l"))
    text = "".join(c for c in text if not unicodedata.category(c).startswith("M"))
    text = "".join(c for c in text if c.isalnum() or c == " ")
    return re.sub(r"\s+", " ", text).strip()


def allowance(n: int) -> int:
    if n < 4:
        return 0
    if n <= 7:
        return 1
    if n <= 15:
        return 2
    return 3


def osa_distance(first: str, second: str) -> int:
    previous_previous = None
    previous = list(range(len(second) + 1))
    for i, a in enumerate(first, 1):
        current = [i]
        for j, b in enumerate(second, 1):
            distance = min(current[j - 1] + 1, previous[j] + 1, previous[j - 1] + (a != b))
            if i > 1 and j > 1 and a == second[j - 2] and first[i - 2] == b:
                distance = min(distance, previous_previous[j - 2] + 1)
            current.append(distance)
        previous_previous, previous = previous, current
    return previous[-1]


def matches_open(typed: str, accepted: list[str], mode: str) -> bool:
    if mode == OpenMatching.EXACT:
        return any(normalize(typed) == normalize(answer) for answer in accepted)
    if mode == OpenMatching.SIMILAR:
        typed = simplify(typed)
        return any(osa_distance(typed, expected) <= allowance(len(expected)) for expected in map(simplify, accepted))
    raise GradingError("Nieobsługiwany sposób dopasowania odpowiedzi.")


def grade(question, selected) -> bool:
    if not isinstance(selected, list):
        raise GradingError("Odpowiedzi muszą być listą.")
    answers = list(question.answers.all())
    if question.type == QuestionType.OPEN:
        if not selected:
            return False
        if len(selected) != 1 or not isinstance(selected[0], str):
            raise GradingError("Pytanie otwarte wymaga jednej odpowiedzi tekstowej.")
        return matches_open(selected[0], [a.text for a in answers if a.is_correct], question.open_matching)
    if question.type not in {QuestionType.SINGLE_CHOICE, QuestionType.MULTIPLE_CHOICE, QuestionType.TRUE_FALSE}:
        raise GradingError("Nieobsługiwany typ pytania.")
    selected_ids = {str(answer) for answer in selected}
    if not selected_ids.issubset({str(answer.id) for answer in answers}):
        raise GradingError("Co najmniej jedna odpowiedź nie należy do tego pytania.")
    return selected_ids == {str(answer.id) for answer in answers if answer.is_correct}
