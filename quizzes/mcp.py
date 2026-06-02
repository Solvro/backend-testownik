from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from mcp_server import MCPToolset
from rest_framework.exceptions import ValidationError

from quizzes.models import (
    AnswerRecord,
    Folder,
    Question,
    QuestionType,
    Quiz,
    QuizSession,
)
from quizzes.permissions import user_has_quiz_read_access
from quizzes.serializers import (
    BulkCreateQuestionsSerializer,
    QuestionSerializer,
    QuizMetaDataSerializer,
    QuizSerializer,
)
from quizzes.services.stats import get_quiz_stats
from testownik_core.mcp_auth import require_scope as _require_scope

CLOSED_QUESTION_INPUTS = {"closed", "normal", "0", 0, QuestionType.CLOSED}
READABLE_VISIBILITY = 2


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


def _question_data(question, request):
    return dict(QuestionSerializer(question, context=_serializer_context(request)).data)


def _quiz_meta_data(quiz, request):
    data = dict(QuizMetaDataSerializer(quiz, context=_serializer_context(request)).data)
    data["question_count"] = getattr(quiz, "questions_count", quiz.questions.count())
    return data


def _quiz_data(quiz, request):
    return dict(QuizSerializer(quiz, context=_serializer_context(request)).data)


def _folder_data(folder):
    return {
        "id": str(folder.id),
        "name": folder.name,
        "folder_type": folder.folder_type,
        "parent_id": str(folder.parent_id) if folder.parent_id else None,
        "quiz_count": getattr(folder, "quiz_count", folder.quizzes.count()),
    }


def _normalize_answers(answers):
    if not isinstance(answers, list):
        raise _QuestionError("answers must be a list of objects.")
    if len(answers) < 2:
        raise _QuestionError("Normal questions require at least two answers.")
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


def _normalize_question_spec(spec):
    if not isinstance(spec, dict):
        raise _QuestionError("Each question must be an object.")

    question_type = spec.get("question_type", "closed")
    if question_type not in CLOSED_QUESTION_INPUTS:
        raise _QuestionError(
            "MCP only supports normal questions. Use answers=[{text, is_correct}] instead of open or true_false."
        )

    data = {
        "text": spec.get("text", ""),
        "question_type": QuestionType.CLOSED,
        "multiple": bool(spec.get("multiple", False)),
        "explanation": spec.get("explanation", "") or "",
        "is_flashcard": bool(spec.get("is_flashcard", False)),
        "is_ai_generated": True,
        "answers": _normalize_answers(spec.get("answers") or []),
    }

    for optional_field in ("image_url", "image_upload", "is_markdown_enabled"):
        if optional_field in spec:
            data[optional_field] = spec[optional_field]
    return data


def _normalize_question_update(*, text=None, explanation=None, answers=None, multiple=None):
    data = {}
    if text is not None:
        data["text"] = text
    if explanation is not None:
        data["explanation"] = explanation
    if multiple is not None:
        data["multiple"] = multiple
    if answers is not None:
        data["answers"] = _normalize_answers(answers)
    return data


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


class QuizTools(MCPToolset):
    def list_my_quizzes(self) -> list[dict]:
        """List all quizzes owned by the current user. Returns quiz id, title,
        description, question count, and visibility."""
        _require_scope(self.request, "quizzes:read")
        user = self.request.user
        quizzes = (
            Quiz.objects.filter(folder__owner=user, archived_at__isnull=True)
            .select_related("creator")
            .annotate(questions_count=Count("questions"))
            .order_by("-updated_at")
        )
        return [_quiz_meta_data(q, self.request) for q in quizzes]

    def search_quizzes(self, query: str) -> list[dict]:
        """Search accessible quizzes by title. Returns matching quizzes the
        current user can read."""
        _require_scope(self.request, "quizzes:read")
        user = self.request.user
        base = Quiz.objects.filter(title__icontains=query, archived_at__isnull=True)
        accessible = base.filter(
            Q(folder__owner=user)
            | Q(visibility__gte=READABLE_VISIBILITY)
            | Q(sharedquiz__user=user, visibility__gte=1)
            | Q(
                sharedquiz__study_group__in=user.study_groups.all(),
                visibility__gte=1,
            )
        ).distinct()
        accessible = accessible.select_related("creator").annotate(questions_count=Count("questions"))[:25]
        return [_quiz_meta_data(q, self.request) for q in accessible]

    def get_quiz(self, quiz_id: str) -> dict:
        """Get full quiz details including all questions and answers."""
        _require_scope(self.request, "quizzes:read")
        user = self.request.user
        try:
            quiz = Quiz.objects.prefetch_related("questions__answers").get(pk=quiz_id)
        except Quiz.DoesNotExist:
            return {"error": "Quiz not found."}
        if not user_has_quiz_read_access(user, quiz):
            return {"error": "You do not have access to this quiz."}
        return _quiz_data(quiz, self.request)

    def get_quiz_questions(self, quiz_id: str) -> list[dict]:
        """List all questions in a quiz with their answers."""
        _require_scope(self.request, "quizzes:read")
        user = self.request.user
        try:
            quiz = Quiz.objects.prefetch_related("questions__answers", "questions__image_upload").get(pk=quiz_id)
        except Quiz.DoesNotExist:
            return [{"error": "Quiz not found."}]
        if not user_has_quiz_read_access(user, quiz):
            return [{"error": "You do not have access to this quiz."}]
        return [_question_data(q, self.request) for q in quiz.questions.all()]

    def create_quiz(
        self,
        title: str,
        description: str = "",
        visibility: int = 2,
        questions: list[dict] | None = None,
    ) -> dict:
        """Create a new quiz, optionally with its questions in a single call.

        Visibility: 0=private, 1=shared only, 2=unlisted (with link), 3=public.

        `questions` (optional): a list of question objects. Each object accepts:
          - text (str): the question prompt
          - answers (list): at least two {text, is_correct} objects. Each answer
            is a normal answer option marked true or false with is_correct.
          - multiple (bool): optional explicit UI/selection setting. It is never
            inferred from how many answers have is_correct=true.
          - explanation (str), is_flashcard (bool): optional

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
                quiz = Quiz.objects.create(
                    title=title,
                    description=description,
                    visibility=visibility,
                    creator=user,
                    folder=user.root_folder,
                    is_ai_generated=True,
                )
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
        except ValidationError as exc:
            return _validation_error(exc.detail)
        return {
            "id": str(quiz.id),
            "title": quiz.title,
            "questions_created": created,
            "status": "created",
        }

    def add_question(
        self,
        quiz_id: str,
        text: str,
        answers: list[dict] | None = None,
        multiple: bool = False,
        explanation: str = "",
        is_flashcard: bool = False,
    ) -> dict:
        """Add a single question to an existing quiz. Marked is_ai_generated=true.

        Pass `answers` as at least two {text, is_correct} objects. Each answer is
        a normal answer option marked true or false with is_correct. `multiple`
        is an explicit UI/selection setting and is not inferred from correctness.

        To add many questions at once, use add_questions instead."""
        _require_scope(self.request, "quizzes:write")
        user = self.request.user
        try:
            quiz = Quiz.objects.get(pk=quiz_id)
        except Quiz.DoesNotExist:
            return {"error": "Quiz not found."}
        if not quiz.can_edit(user):
            return {"error": "You do not have permission to edit this quiz."}

        spec = {
            "text": text,
            "answers": answers,
            "multiple": multiple,
            "explanation": explanation,
            "is_flashcard": is_flashcard,
        }
        try:
            question = _create_single_question(quiz, spec, self.request)
        except _QuestionError as exc:
            return {"error": str(exc)}
        except ValidationError as exc:
            return _validation_error(exc.detail)
        return {"id": str(question.id), "status": "created"}

    def add_questions(self, quiz_id: str, questions: list[dict]) -> dict:
        """Batch-add multiple questions to a quiz in one call. Marked
        is_ai_generated=true.

        `questions`: a list of question objects with the same shape as
        add_question (text, answers, multiple, explanation, is_flashcard). This
        is the preferred way to add more than one question — it is atomic, so if
        any question is invalid nothing is saved and the error names the
        offending index."""
        _require_scope(self.request, "quizzes:write")
        user = self.request.user
        try:
            quiz = Quiz.objects.get(pk=quiz_id)
        except Quiz.DoesNotExist:
            return {"error": "Quiz not found."}
        if not quiz.can_edit(user):
            return {"error": "You do not have permission to edit this quiz."}
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
        answers. Each answer must be a {text, is_correct} object. Passing
        `multiple` explicitly changes the UI/selection setting."""
        _require_scope(self.request, "quizzes:write")
        user = self.request.user
        try:
            question = Question.objects.select_related("quiz").get(pk=question_id)
        except Question.DoesNotExist:
            return {"error": "Question not found."}
        if not question.quiz.can_edit(user):
            return {"error": "You do not have permission to edit this question."}

        if question.question_type != QuestionType.CLOSED:
            return {"error": "MCP only supports editing normal questions."}
        try:
            data = _normalize_question_update(
                text=text,
                explanation=explanation,
                answers=answers,
                multiple=multiple,
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

    def delete_question(self, question_id: str) -> dict:
        """Remove a question from a quiz."""
        _require_scope(self.request, "quizzes:write")
        user = self.request.user
        try:
            question = Question.objects.select_related("quiz").get(pk=question_id)
        except Question.DoesNotExist:
            return {"error": "Question not found."}
        if not question.quiz.can_edit(user):
            return {"error": "You do not have permission to delete this question."}
        question.delete()
        return {"status": "deleted"}


class StudyTools(MCPToolset):
    def get_quiz_session(self, quiz_id: str) -> dict:
        """Get or create an active study session for a quiz. Returns session
        state, progress counts, and the current question."""
        _require_scope(self.request, "study:read")
        user = self.request.user
        try:
            quiz = Quiz.objects.prefetch_related("questions__answers").get(pk=quiz_id)
        except Quiz.DoesNotExist:
            return {"error": "Quiz not found."}
        if not user_has_quiz_read_access(user, quiz):
            return {"error": "You do not have access to this quiz."}
        session, created = QuizSession.get_or_create_active(quiz, user)
        current_q = None
        if session.current_question_id:
            try:
                q = Question.objects.prefetch_related("answers").get(pk=session.current_question_id)
                current_q = _question_data(q, self.request)
            except Question.DoesNotExist:
                pass
        return {
            "session_id": str(session.id),
            "quiz_id": str(quiz.id),
            "quiz_title": quiz.title,
            "is_new": created,
            "correct_count": session.correct_count,
            "wrong_count": session.wrong_count,
            "total_questions": quiz.questions.count(),
            "study_time_seconds": session.study_time.total_seconds(),
            "current_question": current_q,
        }

    def reset_quiz_session(self, quiz_id: str) -> dict:
        """Archive the current session and start a fresh one."""
        _require_scope(self.request, "study:write")
        user = self.request.user
        try:
            quiz = Quiz.objects.get(pk=quiz_id)
        except Quiz.DoesNotExist:
            return {"error": "Quiz not found."}
        if not user_has_quiz_read_access(user, quiz):
            return {"error": "You do not have access to this quiz."}
        with transaction.atomic():
            QuizSession.objects.filter(quiz=quiz, user=user, is_active=True).update(
                is_active=False, ended_at=timezone.now()
            )
            session, _ = QuizSession.get_or_create_active(quiz, user)
        return {
            "session_id": str(session.id),
            "status": "reset",
            "total_questions": quiz.questions.count(),
        }

    def get_next_question(self, quiz_id: str) -> dict:
        """Get the next question to study based on the session's current state."""
        _require_scope(self.request, "study:read")
        user = self.request.user
        try:
            quiz = Quiz.objects.prefetch_related("questions__answers").get(pk=quiz_id)
        except Quiz.DoesNotExist:
            return {"error": "Quiz not found."}
        if not user_has_quiz_read_access(user, quiz):
            return {"error": "You do not have access to this quiz."}
        session, _ = QuizSession.get_or_create_active(quiz, user)
        if session.current_question_id:
            try:
                q = Question.objects.prefetch_related("answers").get(pk=session.current_question_id)
                return _question_data(q, self.request)
            except Question.DoesNotExist:
                pass
        q = quiz.questions.order_by("?").first()
        if q is None:
            return {"error": "This quiz has no questions."}
        session.current_question = q
        session.save(update_fields=["current_question"])
        return _question_data(q, self.request)

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
        user = self.request.user
        try:
            quiz = Quiz.objects.get(pk=quiz_id)
        except Quiz.DoesNotExist:
            return {"error": "Quiz not found."}
        if not user_has_quiz_read_access(user, quiz):
            return {"error": "You do not have access to this quiz."}

        session, _ = QuizSession.get_or_create_active(quiz, user)
        try:
            question = Question.objects.prefetch_related("answers").get(id=question_id, quiz=quiz)
        except Question.DoesNotExist:
            return {"error": "Question not found in this quiz."}

        if question.question_type != QuestionType.CLOSED:
            return {"error": "MCP only supports submitting answers for normal questions."}

        answers = list(question.answers.all())
        selected_ids = set(str(a) for a in selected_answers)
        valid_ids = set(str(a.id) for a in answers)
        if not selected_ids.issubset(valid_ids):
            return {"error": "One or more selected answers are invalid."}
        correct_ids = set(str(a.id) for a in answers if a.is_correct)
        was_correct = correct_ids == selected_ids
        recorded = list(selected_ids)

        AnswerRecord.objects.create(
            session=session,
            question=question,
            selected_answers=recorded,
            was_correct=was_correct,
        )
        session.save(update_fields=["updated_at"])

        correct_answers = [{"id": str(a.id), "text": a.text} for a in question.answers.all() if a.is_correct]

        next_q = quiz.questions.order_by("?").first()
        if next_q:
            session.current_question = next_q
            session.save(update_fields=["current_question"])

        return {
            "was_correct": was_correct,
            "correct_answers": correct_answers,
            "correct_count": session.correct_count,
            "wrong_count": session.wrong_count,
            "next_question_id": str(next_q.id) if next_q else None,
        }

    def get_random_question(self) -> dict:
        """Get a random question from the user's recently active quizzes
        (last 90 days)."""
        _require_scope(self.request, "study:read")
        user = self.request.user
        recent_quiz_ids = list(
            QuizSession.objects.filter(
                user=user,
                is_active=True,
                started_at__gte=timezone.now() - timedelta(days=90),
            ).values_list("quiz_id", flat=True)
        )
        if not recent_quiz_ids:
            return {"error": "No recent quizzes found."}
        question = (
            Question.objects.filter(quiz_id__in=recent_quiz_ids)
            .select_related("quiz")
            .prefetch_related("answers")
            .order_by("?")
            .first()
        )
        if question is None:
            return {"error": "No questions found in recent quizzes."}
        data = _question_data(question, self.request)
        data["quiz_id"] = str(question.quiz.id)
        data["quiz_title"] = question.quiz.title
        return data


class ProgressTools(MCPToolset):
    def get_quiz_progress(self, quiz_id: str) -> dict:
        """Get the user's study progress on a specific quiz, including session
        counts, scores, and study time."""
        _require_scope(self.request, "study:read")
        user = self.request.user
        try:
            quiz = Quiz.objects.get(pk=quiz_id)
        except Quiz.DoesNotExist:
            return {"error": "Quiz not found."}
        if not user_has_quiz_read_access(user, quiz):
            return {"error": "You do not have access to this quiz."}
        return get_quiz_stats(quiz, user)

    def get_quiz_statistics(self, quiz_id: str) -> dict:
        """Get aggregated statistics for a quiz with per-question breakdown."""
        _require_scope(self.request, "study:read")
        user = self.request.user
        try:
            quiz = Quiz.objects.get(pk=quiz_id)
        except Quiz.DoesNotExist:
            return {"error": "Quiz not found."}
        if not user_has_quiz_read_access(user, quiz):
            return {"error": "You do not have access to this quiz."}
        return get_quiz_stats(quiz, user, include_per_question=True)


class FolderTools(MCPToolset):
    def list_folders(self) -> list[dict]:
        """List the current user's quiz folders."""
        _require_scope(self.request, "quizzes:read")
        user = self.request.user
        folders = Folder.objects.filter(owner=user).order_by("-created_at")
        return [_folder_data(folder) for folder in folders]

    def get_folder_quizzes(self, folder_id: str) -> list[dict]:
        """Get all quizzes in a specific folder."""
        _require_scope(self.request, "quizzes:read")
        user = self.request.user
        try:
            folder = Folder.objects.get(pk=folder_id)
        except Folder.DoesNotExist:
            return [{"error": "Folder not found."}]
        if folder.owner != user and not folder.has_edit_permission(user):
            return [{"error": "You do not have access to this folder."}]
        quizzes = (
            Quiz.objects.filter(folder=folder, archived_at__isnull=True)
            .select_related("creator")
            .annotate(questions_count=Count("questions"))
        )
        return [_quiz_meta_data(q, self.request) for q in quizzes]

    def add_quiz_to_folder(self, quiz_id: str, folder_id: str) -> dict:
        """Move a quiz to a different folder."""
        _require_scope(self.request, "quizzes:write")
        user = self.request.user
        try:
            quiz = Quiz.objects.get(pk=quiz_id)
        except Quiz.DoesNotExist:
            return {"error": "Quiz not found."}
        if quiz.folder.owner != user:
            return {"error": "Only the quiz owner can move it."}
        try:
            folder = Folder.objects.get(pk=folder_id, owner=user)
        except Folder.DoesNotExist:
            return {"error": "Folder not found."}
        quiz.folder = folder
        quiz.archived_at = None
        quiz.save(update_fields=["folder", "archived_at", "updated_at"])
        return {"status": "moved", "quiz_id": str(quiz.id), "folder_id": str(folder.id)}
