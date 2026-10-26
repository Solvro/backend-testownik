import random
from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from quizzes.models import (
    AnswerRecord,
    FolderType,
    Question,
    Quiz,
    QuizSession,
    SharedQuiz,
)
from quizzes.permissions import DELETED_QUIZ_MESSAGE, not_guest_owned_q, quiz_is_deleted, user_has_quiz_read_access
from quizzes.services.grading import GradingError, grade

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
        Quiz.objects.filter(folder__owner=user, folder__folder_type=FolderType.REGULAR)
        .select_related("creator")
        .annotate(questions_count=Count("questions"))
        .order_by("-updated_at")
    )


def searchable_quizzes_queryset(user, query: str):
    base = Quiz.objects.filter(title__icontains=query).exclude(folder__folder_type=FolderType.TRASH)
    return (
        base.filter(
            Q(folder__owner=user)
            | (
                not_guest_owned_q()
                & (
                    Q(visibility__gte=PUBLIC_VISIBILITY)
                    | Q(sharedquiz__user=user, visibility__gte=1)
                    | Q(
                        sharedquiz__study_group__in=user.study_groups.all(),
                        visibility__gte=1,
                    )
                )
            )
        )
        .select_related("creator")
        .annotate(questions_count=Count("questions"))
        .distinct()
    )


def grouped_search_quizzes(user, query: str, *, include_public: bool):
    active_quiz_filter = ~Q(folder__folder_type=FolderType.TRASH)
    active_shared_quiz_filter = ~Q(quiz__folder__folder_type=FolderType.TRASH)
    user_quizzes = Quiz.objects.filter(active_quiz_filter, creator=user, title__icontains=query).select_related(
        "creator"
    )
    shared_quizzes = SharedQuiz.objects.filter(
        active_shared_quiz_filter,
        user=user,
        quiz__title__icontains=query,
        quiz__visibility__gte=1,
    ).select_related("quiz__creator")
    group_quizzes = SharedQuiz.objects.filter(
        active_shared_quiz_filter,
        study_group__in=user.study_groups.all(),
        quiz__title__icontains=query,
        quiz__visibility__gte=1,
    ).select_related("quiz__creator")
    public_quizzes = Quiz.objects.none()
    if include_public:
        public_quizzes = Quiz.objects.filter(
            active_quiz_filter, not_guest_owned_q(), title__icontains=query, visibility__gte=PUBLIC_VISIBILITY
        ).select_related("creator")
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
    if quiz_is_deleted(quiz):
        raise QuizOperationError(DELETED_QUIZ_MESSAGE, status_code=403)
    if not user_has_quiz_read_access(user, quiz):
        raise QuizOperationError("You do not have access to this quiz.", status_code=403)
    return quiz


def get_editable_quiz(user, quiz_id):
    try:
        quiz = Quiz.objects.get(pk=quiz_id)
    except (Quiz.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise QuizOperationError("Quiz not found.", status_code=404) from exc
    if quiz_is_deleted(quiz):
        raise QuizOperationError(DELETED_QUIZ_MESSAGE, status_code=403)
    if not quiz.can_edit(user):
        raise QuizOperationError("You do not have permission to edit this quiz.", status_code=403)
    return quiz


def get_editable_question(user, question_id):
    try:
        question = Question.objects.select_related("quiz").get(pk=question_id)
    except (Question.DoesNotExist, ValueError, TypeError, DjangoValidationError) as exc:
        raise QuizOperationError("Question not found.", status_code=404) from exc
    if quiz_is_deleted(question.quiz):
        raise QuizOperationError(DELETED_QUIZ_MESSAGE, status_code=403)
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
        )
        .values_list("quiz_id", flat=True)
        .distinct()
    )


def get_random_recent_question(user, *, days: int = 90):
    recent_quiz_ids = recently_studied_quiz_ids(user, days=days)
    if not recent_quiz_ids:
        raise QuizOperationError("No recent quizzes found.", status_code=404)

    questions = Question.objects.filter(quiz_id__in=recent_quiz_ids).exclude(quiz__folder__folder_type=FolderType.TRASH)
    total_questions = questions.count()
    if total_questions == 0:
        raise QuizOperationError("No questions found in recent quizzes.", status_code=404)

    random_offset = random.randint(0, total_questions - 1)
    return questions.select_related("quiz").prefetch_related("answers").order_by("id")[random_offset]


def _resolve_answer_correctness(question, selected_answers):
    try:
        return grade(question, selected_answers), selected_answers
    except GradingError as exc:
        raise QuizOperationError(str(exc), status_code=400) from exc


def record_quiz_answer(
    user,
    quiz_id,
    question_id,
    selected_answers,
    *,
    self_assessment=UNSET,
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

    if self_assessment is not UNSET:
        if selected_answers != [] or type(self_assessment) is not bool:
            raise QuizOperationError("Samoocena wymaga pustej listy odpowiedzi i wartości logicznej.", status_code=400)
        was_correct, recorded_answers = self_assessment, []
    else:
        was_correct, recorded_answers = _resolve_answer_correctness(question, selected_answers)
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
