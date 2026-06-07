from django.db import transaction
from django.utils import timezone

from quizzes.models import Answer, QuestionChangeSuggestion, QuestionChangeSuggestionStatus


class SuggestionApplyError(Exception):
    pass


class SuggestionVersionConflict(SuggestionApplyError):
    pass


QUESTION_FIELDS = [
    "order",
    "text",
    "explanation",
    "multiple",
    "question_type",
    "tf_answer",
    "is_flashcard",
    "is_markdown_enabled",
]

ANSWER_FIELDS = ["order", "text", "is_correct"]


def apply_question_change_suggestion(suggestion: QuestionChangeSuggestion, user, force: bool = False):
    with transaction.atomic():
        suggestion = (
            QuestionChangeSuggestion.objects.select_for_update()
            .select_related("comment__quiz", "question__quiz")
            .get(pk=suggestion.pk)
        )

        if suggestion.status != QuestionChangeSuggestionStatus.PENDING:
            raise SuggestionApplyError("Suggestion is not pending.")

        question = suggestion.question
        quiz = suggestion.comment.quiz

        if question.quiz_id != quiz.id:
            raise SuggestionApplyError("Suggestion question does not belong to the comment quiz.")

        if not force and suggestion.base_quiz_version != quiz.version:
            raise SuggestionVersionConflict("Quiz has changed since this suggestion was created.")

        payload = suggestion.payload
        changed_question_fields = []

        for field in QUESTION_FIELDS:
            if field in payload and hasattr(question, field):
                setattr(question, field, payload[field])
                changed_question_fields.append(field)

        if changed_question_fields:
            question.save(update_fields=changed_question_fields)

        if "answers" in payload:
            _apply_answers_snapshot(question, payload["answers"])

        quiz.version += 1
        quiz.save(update_fields=["version", "updated_at"])

        suggestion.status = QuestionChangeSuggestionStatus.ACCEPTED
        suggestion.resolved_by = user
        suggestion.resolved_at = timezone.now()
        suggestion.save(update_fields=["status", "resolved_by", "resolved_at", "updated_at"])

        return suggestion


def reject_question_change_suggestion(suggestion: QuestionChangeSuggestion, user):
    if suggestion.status != QuestionChangeSuggestionStatus.PENDING:
        raise SuggestionApplyError("Suggestion is not pending.")

    suggestion.status = QuestionChangeSuggestionStatus.REJECTED
    suggestion.resolved_by = user
    suggestion.resolved_at = timezone.now()
    suggestion.save(update_fields=["status", "resolved_by", "resolved_at", "updated_at"])
    return suggestion


def _apply_answers_snapshot(question, answers_payload):
    existing_answers = {str(answer.id): answer for answer in question.answers.all()}
    incoming_existing_ids = set()

    for answer_data in answers_payload:
        answer_id = answer_data.get("id")

        if answer_id:
            answer = existing_answers.get(str(answer_id))
            if not answer:
                raise SuggestionApplyError(f"Answer {answer_id} does not belong to this question.")
            incoming_existing_ids.add(str(answer_id))

            changed_fields = []
            for field in ANSWER_FIELDS:
                if field in answer_data:
                    setattr(answer, field, answer_data[field])
                    changed_fields.append(field)

            if changed_fields:
                answer.save(update_fields=changed_fields)
            continue

        Answer.objects.create(
            question=question,
            order=answer_data["order"],
            text=answer_data["text"],
            is_correct=answer_data.get("is_correct", False),
        )

    ids_to_delete = set(existing_answers) - incoming_existing_ids
    if ids_to_delete:
        Answer.objects.filter(id__in=ids_to_delete).delete()
