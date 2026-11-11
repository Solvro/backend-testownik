"""Question invariants shared by REST, nested quiz writes, and MCP."""

from uuid import UUID

from rest_framework.exceptions import ValidationError

from quizzes.models import QuestionType


def validate_unique_ids(rows, *, field="id", error_field="questions"):
    seen = set()
    for row in rows:
        row_id = row.get(field)
        if row_id is None:
            continue
        try:
            row_id = str(UUID(str(row_id)))
        except ValueError:
            row_id = str(row_id).lower()
        if row_id in seen:
            label = "odpowiedzi" if error_field == "answers" else "pytania"
            raise ValidationError({error_field: f"Identyfikator {label} nie może się powtarzać w jednym żądaniu."})
        seen.add(row_id)


def validate_question(data, instance=None):
    question_type = data.get("type", instance.type if instance else QuestionType.SINGLE_CHOICE)
    if question_type not in QuestionType.values:
        raise ValidationError({"type": "Nieprawidłowy typ pytania."})
    # Keyed by string: REST sends UUIDs, MCP and admin may send strings.
    existing = {str(answer.id): answer for answer in instance.answers.all()} if instance else {}
    answers = data.get("answers", list(existing.values()))
    if "answers" in data:
        validate_unique_ids(answers, error_field="answers")

    def value(answer, field, default=None):
        if not isinstance(answer, dict):
            return getattr(answer, field, default)
        if field in answer:
            return answer[field]
        return getattr(existing.get(str(answer.get("id"))), field, default)

    correct_count = sum(bool(value(answer, "is_correct", False)) for answer in answers)
    error = None
    if question_type == QuestionType.TRUE_FALSE:
        if len(answers) != 2 or correct_count != 1:
            error = "Pytanie prawda/fałsz musi mieć dokładnie dwie odpowiedzi, w tym jedną poprawną."
        elif {value(answer, "order") for answer in answers} != {1, 2}:
            error = "Odpowiedzi prawda/fałsz muszą mieć kolejność 1 (prawda) i 2 (fałsz)."
    elif question_type == QuestionType.OPEN:
        if not answers or correct_count != len(answers):
            error = "Pytanie otwarte musi mieć co najmniej jedną odpowiedź i wszystkie muszą być poprawne."
        elif any(value(answer, "image_url") or value(answer, "image_upload") for answer in answers):
            error = "Odpowiedzi na pytanie otwarte nie mogą zawierać obrazów."
    elif question_type == QuestionType.SINGLE_CHOICE and correct_count != 1:
        error = "Pytanie jednokrotnego wyboru musi mieć dokładnie jedną poprawną odpowiedź."
    elif question_type == QuestionType.MULTIPLE_CHOICE and not answers:
        error = "Pytanie wielokrotnego wyboru musi mieć co najmniej jedną odpowiedź."
    if error:
        raise ValidationError({"answers": error})
    if instance is None:
        data.setdefault("type", QuestionType.SINGLE_CHOICE)
    return data
