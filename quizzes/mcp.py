from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.exceptions import ValidationError

from quizzes.models import (
    Question,
    QuestionType,
    Quiz,
)
from quizzes.serializers import (
    BulkCreateQuestionsSerializer,
    QuestionSerializer,
    QuizMetaDataSerializer,
    QuizSerializer,
)
from quizzes.services.operations import (
    QuizOperationError,
    get_current_session_question,
    get_editable_question,
    get_editable_quiz,
    get_or_choose_session_question,
    get_readable_quiz,
    get_readable_session,
    owned_quizzes_queryset,
    record_quiz_answer,
    reset_readable_session,
    searchable_quizzes_queryset,
)
from testownik_core.mcp_auth import require_scope as _require_scope
from testownik_core.mcp_tools import AnnotatedMCPToolset, tool_annotations


class _QuestionError(ValueError):
    """Raised when a question payload is invalid. Message is returned to the agent."""


def _serializer_context(request):
    return {"request": request}


def _plain_data(value):
    if isinstance(value, dict):
        return {key: _plain_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain_data(item) for item in value]
    if isinstance(value, tuple):
        return [_plain_data(item) for item in value]
    return str(value) if value.__class__.__name__ == "ErrorDetail" else value


def _validation_error(errors):
    return {"error": _plain_data(errors)}


def _model_validation_error(exc):
    return _validation_error(getattr(exc, "message_dict", getattr(exc, "messages", str(exc))))


def _operation_error(exc):
    return {"error": exc.message}


def _question_data(question, request):
    return dict(QuestionSerializer(question, context=_serializer_context(request)).data)


def _quiz_meta_data(quiz, request):
    data = dict(QuizMetaDataSerializer(quiz, context=_serializer_context(request)).data)
    data["question_count"] = getattr(quiz, "questions_count", quiz.questions.count())
    return data


def _mcp_quiz_meta_data(quiz, request):
    data = _quiz_meta_data(quiz, request)
    data.pop("visibility", None)
    return data


def _quiz_data(quiz, request):
    return dict(QuizSerializer(quiz, context=_serializer_context(request)).data)


def _normalize_answers(answers):
    if not isinstance(answers, list):
        raise _QuestionError("answers must be a list of objects.")
    if len(answers) < 1:
        raise _QuestionError("Normal questions require at least one answer.")
    if any(not isinstance(answer, dict) for answer in answers):
        raise _QuestionError("Each answer must be an object with text and is_correct.")

    normalized = []
    has_correct = False
    for index, answer in enumerate(answers):
        if "is_correct" not in answer:
            raise _QuestionError(f"answers[{index}] is missing is_correct.")
        normalized_answer = dict(answer)
        normalized_answer.setdefault("order", index + 1)
        normalized_answer["is_correct"] = bool(normalized_answer["is_correct"])
        has_correct = has_correct or normalized_answer["is_correct"]
        normalized.append(normalized_answer)

    if not has_correct:
        raise _QuestionError("Normal questions require at least one correct answer.")
    return normalized


def _correct_answer_count(answers):
    return sum(1 for answer in answers if (answer["is_correct"] if isinstance(answer, dict) else answer.is_correct))


def _normalize_multiple(value, answers):
    correct_count = _correct_answer_count(answers)
    inferred = correct_count > 1
    if value is None:
        return inferred
    if type(value) is not bool:
        raise _QuestionError("multiple must be a boolean.")
    if not value and inferred:
        raise _QuestionError("multiple must be true when more than one answer is correct.")
    return value


def _normalize_question_spec(spec):
    if not isinstance(spec, dict):
        raise _QuestionError("Each question must be an object.")

    answers = _normalize_answers(spec.get("answers") or [])
    data = {
        "text": spec.get("text", ""),
        "question_type": QuestionType.CLOSED,
        "multiple": _normalize_multiple(spec.get("multiple"), answers),
        "explanation": spec.get("explanation", "") or "",
        "is_ai_generated": True,
        "answers": answers,
    }

    for optional_field in ("image_url", "image_upload", "is_markdown_enabled"):
        if optional_field in spec:
            data[optional_field] = spec[optional_field]
    return data


def _normalize_question_update(*, text=None, explanation=None, answers=None, multiple=None, current_answers=None):
    data = {}
    if text is not None:
        data["text"] = text
    if explanation is not None:
        data["explanation"] = explanation
    if answers is not None:
        normalized_answers = _normalize_answers(answers)
        data["answers"] = normalized_answers
        data["multiple"] = _normalize_multiple(multiple, normalized_answers)
    elif multiple is not None:
        data["multiple"] = _normalize_multiple(multiple, current_answers or [])
    return data


def _normalize_question_range(from_index=None, to_index=None):
    if from_index is None and to_index is None:
        return None

    if from_index is not None and type(from_index) is not int:
        raise _QuestionError("from_index must be an integer.")
    if to_index is not None and type(to_index) is not int:
        raise _QuestionError("to_index must be an integer.")
    if from_index is not None and from_index < 1:
        raise _QuestionError("from_index must be greater than or equal to 1.")
    if to_index is not None and to_index < 1:
        raise _QuestionError("to_index must be greater than or equal to 1.")
    if from_index is not None and to_index is not None and from_index > to_index:
        raise _QuestionError("from_index must be less than or equal to to_index.")

    start = from_index - 1 if from_index is not None else None
    stop = to_index if to_index is not None else None
    return slice(start, stop)


def _create_questions(quiz, questions, request):
    serializer = BulkCreateQuestionsSerializer(
        data={"quiz": str(quiz.id), "questions": _normalize_indexed_question_specs(questions)},
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def _create_single_question(quiz, spec, request):
    return _create_questions(quiz, [spec], request)[0]


def _format_question_error(prefix, exc):
    message = str(exc)
    return f"{prefix}: {message}" if prefix else message


def _normalize_indexed_question_specs(questions):
    normalized = []
    for index, spec in enumerate(questions or []):
        try:
            normalized.append(_normalize_question_spec(spec))
        except _QuestionError as exc:
            raise _QuestionError(_format_question_error(f"questions[{index}]", exc)) from exc
    return normalized


class QuizTools(AnnotatedMCPToolset):
    @tool_annotations(title="List my quizzes", read_only=True, destructive=False, idempotent=True)
    def list_my_quizzes(self) -> list[dict]:
        """List all quizzes owned by the current user. Returns quiz id, title,
        description, and question count."""
        _require_scope(self.request, "quizzes:read")
        quizzes = owned_quizzes_queryset(self.request.user)
        return [_mcp_quiz_meta_data(q, self.request) for q in quizzes]

    @tool_annotations(title="Search quizzes", read_only=True, destructive=False, idempotent=True)
    def search_quizzes(self, query: str) -> list[dict]:
        """Search accessible quizzes by title. Returns matching quizzes the
        current user can read."""
        _require_scope(self.request, "quizzes:read")
        accessible = searchable_quizzes_queryset(self.request.user, query)[:25]
        return [_quiz_meta_data(q, self.request) for q in accessible]

    @tool_annotations(title="Get quiz", read_only=True, destructive=False, idempotent=True)
    def get_quiz(self, quiz_id: str) -> dict:
        """Get full quiz details including all questions and answers."""
        _require_scope(self.request, "quizzes:read")
        try:
            quiz = get_readable_quiz(self.request.user, quiz_id, prefetch_questions=True)
        except QuizOperationError as exc:
            return _operation_error(exc)
        return _quiz_data(quiz, self.request)

    @tool_annotations(title="Get quiz questions", read_only=True, destructive=False, idempotent=True)
    def get_quiz_questions(
        self,
        quiz_id: str,
        from_index: int | None = None,
        to_index: int | None = None,
    ) -> dict:
        """List questions in a quiz with their answers.

        Optional `from_index` and `to_index` are 1-based inclusive question
        positions. Omit both to return all questions.
        """
        _require_scope(self.request, "quizzes:read")
        try:
            question_range = _normalize_question_range(from_index, to_index)
        except _QuestionError as exc:
            return {"error": str(exc)}
        try:
            quiz = get_readable_quiz(self.request.user, quiz_id)
        except QuizOperationError as exc:
            return _operation_error(exc)

        questions = (
            Question.objects.filter(quiz=quiz)
            .select_related("image_upload")
            .prefetch_related("answers__image_upload")
            .order_by("order")
        )
        if question_range is not None:
            questions = questions[question_range]
        return {"questions": [_question_data(q, self.request) for q in questions.iterator(chunk_size=500)]}

    @tool_annotations(title="Create quiz", read_only=False, destructive=False, idempotent=False)
    def create_quiz(
        self,
        title: str,
        description: str = "",
        questions: list[dict] | None = None,
    ) -> dict:
        """Create a new quiz, optionally with its questions in a single call.

        `questions` (optional): a list of question objects. Each object accepts:
          - text (str): the question prompt
          - answers (list): at least one {text, is_correct} object. Each answer
            is a normal answer option marked true or false with is_correct.
          - multiple (bool): optional UI/selection setting. If omitted, it is
            inferred from how many answers have is_correct=true.
          - explanation (str): optional

        The quiz and all its questions are flagged is_ai_generated=true so the UI
        can label them. Prefer passing questions here over many add_question calls.
        If any question is invalid, nothing is created and an error pointing to the
        offending index is returned.
        """
        _require_scope(self.request, "quizzes:write")
        if not (title or "").strip():
            return {"error": "title is required."}
        user = self.request.user
        try:
            normalized_questions = _normalize_indexed_question_specs(questions or [])
            with transaction.atomic():
                quiz = Quiz(
                    title=title,
                    description=description,
                    creator=user,
                    folder=user.root_folder,
                    is_ai_generated=True,
                )
                quiz.full_clean()
                quiz.save()
                if normalized_questions:
                    serializer = BulkCreateQuestionsSerializer(
                        data={"quiz": str(quiz.id), "questions": normalized_questions},
                        context=_serializer_context(self.request),
                    )
                    serializer.is_valid(raise_exception=True)
                    serializer.save()
                created = len(normalized_questions)
        except _QuestionError as exc:
            return {"error": str(exc)}
        except DjangoValidationError as exc:
            return _model_validation_error(exc)
        except ValidationError as exc:
            return _validation_error(exc.detail)
        return {
            "id": str(quiz.id),
            "title": quiz.title,
            "questions_created": created,
            "status": "created",
        }

    @tool_annotations(title="Add question", read_only=False, destructive=False, idempotent=False)
    def add_question(
        self,
        quiz_id: str,
        text: str,
        answers: list[dict] | None = None,
        multiple: bool | None = None,
        explanation: str = "",
    ) -> dict:
        """Add a single question to an existing quiz. Marked is_ai_generated=true.

        Pass `answers` as at least one {text, is_correct} object. Each answer is
        a normal answer option marked true or false with is_correct. If `multiple`
        is omitted, it is inferred from the number of correct answers.

        To add many questions at once, use add_questions instead."""
        _require_scope(self.request, "quizzes:write")
        try:
            quiz = get_editable_quiz(self.request.user, quiz_id)
        except QuizOperationError as exc:
            return _operation_error(exc)

        spec = {
            "text": text,
            "answers": answers,
            "multiple": multiple,
            "explanation": explanation,
        }
        try:
            question = _create_single_question(quiz, spec, self.request)
        except _QuestionError as exc:
            return {"error": str(exc)}
        except ValidationError as exc:
            return _validation_error(exc.detail)
        return {"id": str(question.id), "status": "created"}

    @tool_annotations(title="Add questions", read_only=False, destructive=False, idempotent=False)
    def add_questions(self, quiz_id: str, questions: list[dict]) -> dict:
        """Batch-add multiple questions to a quiz in one call. Marked
        is_ai_generated=true.

        `questions`: a list of question objects with the same shape as
        add_question (text, answers, multiple, explanation). This is the
        preferred way to add more than one question — it is atomic, so if
        any question is invalid nothing is saved and the error names the
        offending index."""
        _require_scope(self.request, "quizzes:write")
        try:
            quiz = get_editable_quiz(self.request.user, quiz_id)
        except QuizOperationError as exc:
            return _operation_error(exc)
        if not questions:
            return {"error": "Provide at least one question."}

        try:
            created_questions = _create_questions(quiz, questions, self.request)
        except _QuestionError as exc:
            return {"error": str(exc)}
        except ValidationError as exc:
            return _validation_error(exc.detail)
        created_ids = [str(question.id) for question in created_questions]
        return {"status": "created", "created_count": len(created_ids), "question_ids": created_ids}

    @tool_annotations(title="Edit question", read_only=False, destructive=True, idempotent=False)
    def edit_question(
        self,
        question_id: str,
        text: str | None = None,
        explanation: str | None = None,
        answers: list[dict] | None = None,
        multiple: bool | None = None,
    ) -> dict:
        """Update a normal question's text, explanation, or answers.

        Only provided fields are changed. Passing `answers` replaces all existing
        answers. Each answer must be a {text, is_correct} object. If `answers`
        is provided and `multiple` is omitted, `multiple` is inferred from the
        new answer set."""
        _require_scope(self.request, "quizzes:write")
        try:
            question = get_editable_question(self.request.user, question_id)
        except QuizOperationError as exc:
            return _operation_error(exc)

        if question.question_type != QuestionType.CLOSED:
            return {"error": "MCP only supports editing normal questions."}
        try:
            data = _normalize_question_update(
                text=text,
                explanation=explanation,
                answers=answers,
                multiple=multiple,
                current_answers=list(question.answers.all()),
            )
        except _QuestionError as exc:
            return {"error": str(exc)}
        if not data:
            return {"id": str(question.id), "status": "updated"}

        serializer = QuestionSerializer(
            question,
            data=data,
            partial=True,
            context=_serializer_context(self.request),
        )
        try:
            serializer.is_valid(raise_exception=True)
            serializer.save()
        except ValidationError as exc:
            return _validation_error(exc.detail)
        return {"id": str(question.id), "status": "updated"}

    @tool_annotations(title="Edit questions", read_only=False, destructive=True, idempotent=False)
    def edit_questions(self, updates: list[dict]) -> dict:
        """Batch-edit normal questions in one atomic call.

        Each update object must include question_id and may include text,
        explanation, answers, or multiple. Passing `answers` replaces all
        existing answers for that question. Each answer must be a
        {text, is_correct} object. If `answers` is provided and `multiple` is
        omitted, `multiple` is inferred from the new answer set.
        """
        _require_scope(self.request, "quizzes:write")
        if not updates:
            return {"error": "Provide at least one question update."}
        if any(not isinstance(update, dict) for update in updates):
            return {"error": "Each update must be an object."}

        serializers = []
        try:
            with transaction.atomic():
                for index, update in enumerate(updates):
                    question_id = update.get("question_id")
                    if not question_id:
                        return {"error": f"updates[{index}]: question_id is required."}

                    try:
                        question = get_editable_question(self.request.user, question_id)
                    except QuizOperationError as exc:
                        return {"error": f"updates[{index}]: {exc.message}"}

                    if question.question_type != QuestionType.CLOSED:
                        return {"error": f"updates[{index}]: MCP only supports editing normal questions."}

                    try:
                        data = _normalize_question_update(
                            text=update.get("text"),
                            explanation=update.get("explanation"),
                            answers=update.get("answers"),
                            multiple=update.get("multiple"),
                            current_answers=list(question.answers.all()),
                        )
                    except _QuestionError as exc:
                        return {"error": f"updates[{index}]: {exc}"}

                    if not data:
                        serializers.append((question, None))
                        continue

                    serializer = QuestionSerializer(
                        question,
                        data=data,
                        partial=True,
                        context=_serializer_context(self.request),
                    )
                    try:
                        serializer.is_valid(raise_exception=True)
                    except ValidationError as exc:
                        return {"error": {f"updates[{index}]": _plain_data(exc.detail)}}
                    serializers.append((question, serializer))

                updated_ids = []
                for question, serializer in serializers:
                    if serializer is not None:
                        serializer.save()
                    updated_ids.append(str(question.id))
        except ValidationError as exc:
            return _validation_error(exc.detail)

        return {"status": "updated", "updated_count": len(updated_ids), "question_ids": updated_ids}

    @tool_annotations(title="Delete question", read_only=False, destructive=True, idempotent=True)
    def delete_question(self, question_id: str) -> dict:
        """Remove a question from a quiz."""
        _require_scope(self.request, "quizzes:write")
        try:
            question = get_editable_question(self.request.user, question_id)
        except QuizOperationError as exc:
            return _operation_error(exc)
        question.delete()
        return {"status": "deleted"}


class StudyTools(AnnotatedMCPToolset):
    @tool_annotations(title="Get quiz session", read_only=True, destructive=False, idempotent=False)
    def get_quiz_session(self, quiz_id: str) -> dict:
        """Get or create an active study session for a quiz. Returns session
        state, progress counts, and the current question."""
        _require_scope(self.request, "study:read")
        try:
            state = get_readable_session(self.request.user, quiz_id, prefetch_quiz=True)
        except QuizOperationError as exc:
            return _operation_error(exc)
        session = state.session
        quiz = state.quiz
        current_q = get_current_session_question(session)
        return {
            "session_id": str(session.id),
            "quiz_id": str(quiz.id),
            "quiz_title": quiz.title,
            "is_new": state.created,
            "correct_count": session.correct_count,
            "wrong_count": session.wrong_count,
            "total_questions": quiz.questions.count(),
            "study_time_seconds": session.study_time.total_seconds(),
            "current_question": _question_data(current_q, self.request) if current_q else None,
        }

    @tool_annotations(title="Reset quiz session", read_only=False, destructive=True, idempotent=False)
    def reset_quiz_session(self, quiz_id: str) -> dict:
        """Archive the current session and start a fresh one."""
        _require_scope(self.request, "study:write")
        try:
            state = reset_readable_session(self.request.user, quiz_id)
        except QuizOperationError as exc:
            return _operation_error(exc)
        return {
            "session_id": str(state.session.id),
            "status": "reset",
            "total_questions": state.quiz.questions.count(),
        }

    @tool_annotations(title="Get next question", read_only=True, destructive=False, idempotent=False)
    def get_next_question(self, quiz_id: str) -> dict:
        """Get the next question to study based on the session's current state."""
        _require_scope(self.request, "study:read")
        try:
            state = get_readable_session(self.request.user, quiz_id, prefetch_quiz=True)
            question = get_or_choose_session_question(state.session, state.quiz)
        except QuizOperationError as exc:
            return _operation_error(exc)
        return _question_data(question, self.request)

    @tool_annotations(title="Submit answer", read_only=False, destructive=False, idempotent=False)
    def submit_answer(
        self,
        quiz_id: str,
        question_id: str,
        selected_answers: list,
    ) -> dict:
        """Submit an answer for a question in the current study session.
        Pass a list of selected answer UUIDs for normal questions.
        Returns whether the answer was correct and the updated session state."""
        _require_scope(self.request, "study:write")
        try:
            result = record_quiz_answer(
                self.request.user,
                quiz_id,
                question_id,
                selected_answers,
                closed_only=True,
                choose_random_next=True,
            )
        except QuizOperationError as exc:
            return _operation_error(exc)

        correct_answers = [
            {"id": str(answer.id), "text": answer.text} for answer in result.question.answers.all() if answer.is_correct
        ]

        return {
            "was_correct": result.was_correct,
            "correct_answers": correct_answers,
            "correct_count": result.session.correct_count,
            "wrong_count": result.session.wrong_count,
            "next_question_id": str(result.session.current_question_id) if result.session.current_question_id else None,
        }
