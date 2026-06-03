import random
from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from quizzes.models import (
    AnswerRecord,
    Folder,
    Question,
    QuestionType,
    Quiz,
    QuizSession,
    SharedQuiz,
)
from quizzes.permissions import user_has_quiz_read_access
from quizzes.services.normalizer import normalize

PUBLIC_VISIBILITY = 3
UNSET = object()


class QuizOperationError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class SessionState:
    session: QuizSession
    quiz: Quiz
    created: bool = False


@dataclass(frozen=True)
class AnswerResult:
    record: AnswerRecord
    session: QuizSession
    question: Question
    was_correct: bool
    selected_answers: list


def owned_quizzes_queryset(user):
    return (
        Quiz.objects.filter(folder__owner=user, archived_at__isnull=True)
        .select_related("creator")
        .annotate(questions_count=Count("questions"))
        .order_by("-updated_at")
    )


def searchable_quizzes_queryset(user, query: str):
    base = Quiz.objects.filter(title__icontains=query, archived_at__isnull=True)
    return (
        base.filter(
            Q(folder__owner=user)
            | Q(visibility__gte=PUBLIC_VISIBILITY)
            | Q(sharedquiz__user=user, visibility__gte=1)
            | Q(
                sharedquiz__study_group__in=user.study_groups.all(),
                visibility__gte=1,
            )
        )
        .select_related("creator")
        .annotate(questions_count=Count("questions"))
        .distinct()
    )


def grouped_search_quizzes(user, query: str, *, include_public: bool):
    user_quizzes = Quiz.objects.filter(creator=user, title__icontains=query).select_related("creator")
    shared_quizzes = SharedQuiz.objects.filter(
        user=user,
        quiz__title__icontains=query,
        quiz__visibility__gte=1,
    ).select_related("quiz__creator")
    group_quizzes = SharedQuiz.objects.filter(
        study_group__in=user.study_groups.all(),
        quiz__title__icontains=query,
        quiz__visibility__gte=1,
    ).select_related("quiz__creator")
    public_quizzes = Quiz.objects.none()
    if include_public:
        public_quizzes = Quiz.objects.filter(title__icontains=query, visibility__gte=PUBLIC_VISIBILITY).select_related(
            "creator"
        )
    return {
        "user_quizzes": user_quizzes,
        "shared_quizzes": [share.quiz for share in shared_quizzes],
        "group_quizzes": [share.quiz for share in group_quizzes],
        "public_quizzes": public_quizzes,
    }


def get_readable_quiz(user, quiz_id, *, queryset=None, prefetch_questions: bool = False):
    queryset = queryset or Quiz.objects.all()
    if prefetch_questions:
        queryset = queryset.prefetch_related("questions__answers")
    try:
        quiz = queryset.get(pk=quiz_id)
    except (Quiz.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise QuizOperationError("Quiz not found.", status_code=404) from exc
    if not user_has_quiz_read_access(user, quiz):
        raise QuizOperationError("You do not have access to this quiz.", status_code=403)
    return quiz


def get_editable_quiz(user, quiz_id):
    try:
        quiz = Quiz.objects.get(pk=quiz_id)
    except (Quiz.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise QuizOperationError("Quiz not found.", status_code=404) from exc
    if not quiz.can_edit(user):
        raise QuizOperationError("You do not have permission to edit this quiz.", status_code=403)
    return quiz


def get_editable_question(user, question_id):
    try:
        question = Question.objects.select_related("quiz").get(pk=question_id)
    except (Question.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise QuizOperationError("Question not found.", status_code=404) from exc
    if not question.quiz.can_edit(user):
        raise QuizOperationError("You do not have permission to edit this question.", status_code=403)
    return question


def get_readable_session(user, quiz_id, *, prefetch_quiz: bool = False) -> SessionState:
    quiz = get_readable_quiz(user, quiz_id, prefetch_questions=prefetch_quiz)
    session, created = QuizSession.get_or_create_active(quiz, user)
    return SessionState(session=session, quiz=quiz, created=created)


def reset_readable_session(user, quiz_id) -> SessionState:
    quiz = get_readable_quiz(user, quiz_id)
    with transaction.atomic():
        QuizSession.objects.filter(quiz=quiz, user=user, is_active=True).update(
            is_active=False,
            ended_at=timezone.now(),
        )
        session, created = QuizSession.get_or_create_active(quiz, user)
    return SessionState(session=session, quiz=quiz, created=created)


def get_current_session_question(session):
    if not session.current_question_id:
        return None
    try:
        return Question.objects.prefetch_related("answers").get(pk=session.current_question_id)
    except Question.DoesNotExist:
        return None


def get_or_choose_session_question(session, quiz):
    question = get_current_session_question(session)
    if question is not None:
        return question

    question = quiz.questions.order_by("?").first()
    if question is None:
        raise QuizOperationError("This quiz has no questions.", status_code=404)
    session.current_question = question
    session.save(update_fields=["current_question"])
    return question


def recently_studied_quiz_ids(user, *, days: int = 90):
    return list(
        QuizSession.objects.filter(
            user=user,
            updated_at__gte=timezone.now() - timedelta(days=days),
        ).values_list("quiz_id", flat=True)
    )


def get_random_recent_question(user, *, days: int = 90):
    recent_quiz_ids = recently_studied_quiz_ids(user, days=days)
    if not recent_quiz_ids:
        raise QuizOperationError("No recent quizzes found.", status_code=404)

    total_questions = Question.objects.filter(quiz_id__in=recent_quiz_ids).count()
    if total_questions == 0:
        raise QuizOperationError("No questions found in recent quizzes.", status_code=404)

    random_offset = random.randint(0, total_questions - 1)
    return (
        Question.objects.filter(quiz_id__in=recent_quiz_ids)
        .select_related("quiz")
        .prefetch_related("answers")
        .order_by("id")[random_offset]
    )


def _resolve_answer_correctness(question, selected_answers, *, closed_only: bool):
    if closed_only and question.question_type != QuestionType.CLOSED:
        raise QuizOperationError("MCP only supports submitting answers for normal questions.", status_code=400)

    if question.question_type == QuestionType.CLOSED:
        answers = list(question.answers.all())
        selected_ids = set(str(answer) for answer in selected_answers)
        valid_answer_ids = set(str(answer.id) for answer in answers)
        if not selected_ids.issubset(valid_answer_ids):
            message = (
                "One or more selected answers are invalid"
                if closed_only
                else "One or more selected answers do not belong to this question"
            )
            raise QuizOperationError(message, status_code=400)
        correct_answer_ids = set(str(answer.id) for answer in answers if answer.is_correct)
        return correct_answer_ids == selected_ids, list(selected_ids)

    if question.question_type == QuestionType.TRUE_FALSE:
        if len(selected_answers) > 1:
            raise QuizOperationError("Invalid list size for this question type", status_code=400)
        if question.tf_answer is None:
            raise QuizOperationError("Question does not have tf answer", status_code=500)
        user_answer = selected_answers[0]
        if not isinstance(user_answer, bool):
            raise QuizOperationError("Invalid data type", status_code=400)
        return user_answer == question.tf_answer, selected_answers

    if question.question_type == QuestionType.OPEN:
        if len(selected_answers) > 1:
            raise QuizOperationError("Invalid list size for this question type", status_code=400)
        input_text = selected_answers[0]
        if not isinstance(input_text, str):
            raise QuizOperationError("Invalid data type", status_code=400)
        correct_answer = question.answers.filter(is_correct=True).first()
        if correct_answer is None:
            raise QuizOperationError("Question has no correct answer", status_code=500)
        return normalize(input_text) == normalize(correct_answer.text), selected_answers

    raise QuizOperationError("Unsupported question type", status_code=400)


def record_quiz_answer(
    user,
    quiz_id,
    question_id,
    selected_answers,
    *,
    closed_only: bool = False,
    study_time=None,
    next_question_id=UNSET,
    choose_random_next: bool = False,
) -> AnswerResult:
    state = get_readable_session(user, quiz_id)
    quiz = state.quiz
    session = state.session

    try:
        question = Question.objects.prefetch_related("answers").get(id=question_id, quiz=quiz)
    except (Question.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise QuizOperationError("Question not found in this quiz", status_code=404) from exc

    was_correct, recorded_answers = _resolve_answer_correctness(question, selected_answers, closed_only=closed_only)
    record = AnswerRecord.objects.create(
        session=session,
        question=question,
        selected_answers=list(recorded_answers),
        was_correct=was_correct,
    )

    update_fields = ["updated_at"]
    if study_time is not None:
        try:
            session.study_time = timedelta(seconds=float(study_time))
        except (TypeError, ValueError) as exc:
            raise QuizOperationError("study_time must be a numeric value", status_code=400) from exc
        update_fields.append("study_time")

    if next_question_id is not UNSET:
        if next_question_id is not None:
            try:
                exists = Question.objects.filter(id=next_question_id, quiz=quiz).exists()
            except (ValueError, TypeError, DjangoValidationError) as exc:
                raise QuizOperationError(
                    "next_question must be a valid question in this quiz", status_code=400
                ) from exc
            if not exists:
                raise QuizOperationError("next_question must be a valid question in this quiz", status_code=400)
        session.current_question_id = next_question_id
        update_fields.append("current_question_id")
    elif choose_random_next:
        next_question = quiz.questions.order_by("?").first()
        if next_question:
            session.current_question = next_question
            update_fields.append("current_question")

    session.save(update_fields=update_fields)
    return AnswerResult(
        record=record,
        session=session,
        question=question,
        was_correct=was_correct,
        selected_answers=list(recorded_answers),
    )


def get_folder_for_read(user, folder_id):
    try:
        folder = Folder.objects.get(pk=folder_id)
    except (Folder.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise QuizOperationError("Folder not found.", status_code=404) from exc
    if folder.owner != user and not folder.has_edit_permission(user):
        raise QuizOperationError("You do not have access to this folder.", status_code=403)
    return folder


def folder_quizzes_queryset(folder):
    return (
        Quiz.objects.filter(folder=folder, archived_at__isnull=True)
        .select_related("creator")
        .annotate(questions_count=Count("questions"))
    )


def move_owned_quiz(user, quiz_id, folder_id):
    try:
        quiz = Quiz.objects.get(pk=quiz_id)
    except (Quiz.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise QuizOperationError("Quiz not found.", status_code=404) from exc
    if quiz.folder.owner != user:
        raise QuizOperationError("Only the quiz owner can move it.", status_code=403)
    try:
        folder = Folder.objects.get(pk=folder_id, owner=user)
    except (Folder.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise QuizOperationError("Folder not found.", status_code=404) from exc
    quiz.folder = folder
    quiz.archived_at = None
    quiz.save(update_fields=["folder", "archived_at", "updated_at"])
    return quiz, folder
