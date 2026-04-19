import logging
import random
import urllib.parse
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Avg, Count, Prefetch, Q
from django.utils import timezone
from django.utils.html import escape
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from quizzes.models import (
    Answer,
    AnswerRecord,
    Comment,
    Folder,
    Question,
    QuestionType,
    Quiz,
    QuizRating,
    QuizSession,
    SharedQuiz,
)
from quizzes.permissions import (
    IsCommentAuthorOrReadOnly,
    IsFolderOwner,
    IsInternalApiRequest,
    IsQuestionReadable,
    IsQuizCreator,
    IsQuizCreatorOrCollaboratorOrReadOnly,
    IsQuizReadable,
    IsRatingUserOrReadOnly,
    IsSharedQuizCreatorOrReadOnly,
    user_has_quiz_read_access,
)
from quizzes.serializers import (
    AnswerRecordSerializer,
    AnswerSerializer,
    CommentSerializer,
    FolderSerializer,
    LibraryItemSerializer,
    MoveFolderSerializer,
    MoveQuizSerializer,
    QuestionSerializer,
    QuizMetaDataSerializer,
    QuizMetaDataWithQuestionSerializer,
    QuizRatingSerializer,
    QuizSearchResultSerializer,
    QuizSerializer,
    QuizSessionSerializer,
    RecordAnswerSerializer,
    SharedQuizSerializer,
)
from quizzes.services.metadata import get_preview_question
from quizzes.services.normalizer import normalize
from quizzes.services.notifications import (
    notify_quiz_shared_to_groups,
    notify_quiz_shared_to_users,
)
from quizzes.throttling import CopyQuizThrottle
from testownik_core.emails import send_email
from users.models import AccountType

logger = logging.getLogger(__name__)


class RandomQuestionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get random question from recent quizzes",
        responses={
            200: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "text": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "quiz_id": {"type": "string", "format": "uuid"},
                        "quiz_title": {"type": "string"},
                    },
                },
                description="Randomly selected question from user's recent quizzes",
            ),
            401: OpenApiResponse(description="Unauthorized"),
            404: OpenApiResponse(description="No quizzes found"),
        },
        examples=[
            OpenApiExample(
                "Random question response",
                value={
                    "id": "q1",
                    "text": "What is the capital of France?",
                    "options": ["Paris", "London", "Berlin", "Madrid"],
                    "quiz_id": "123e4567-e89b-12d3-a456-426614174000",
                    "quiz_title": "Geography Quiz",
                },
                status_codes=["200"],
            )
        ],
    )
    def get(self, request):
        recent_quiz_ids = list(
            QuizSession.objects.filter(
                user=request.user,
                is_active=True,
                started_at__gte=timezone.now() - timedelta(days=90),
            ).values_list("quiz_id", flat=True)
        )

        if not recent_quiz_ids:
            return Response({"error": "No quizzes found"}, status=404)
        total_questions = Question.objects.filter(quiz_id__in=recent_quiz_ids).count()
        if total_questions == 0:
            return Response({"error": "No quizzes found"}, status=404)

        random_offset = random.randint(0, total_questions - 1)
        random_question = (
            Question.objects.filter(quiz_id__in=recent_quiz_ids)
            .select_related("quiz")
            .prefetch_related("answers")[random_offset]
        )

        return Response(
            {
                "id": str(random_question.id),
                "text": random_question.text,
                "answers": AnswerSerializer(random_question.answers.all(), many=True).data,
                "quiz_id": random_question.quiz.id,
                "quiz_title": random_question.quiz.title,
            }
        )


class LastUsedQuizzesView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = QuizMetaDataSerializer
    pagination_class = LimitOffsetPagination

    @extend_schema(
        summary="Get recently used quizzes",
        responses={
            200: QuizMetaDataSerializer(many=True),
            401: OpenApiResponse(description="Unauthorized"),
        },
    )
    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        user_ratings = Prefetch("ratings", queryset=QuizRating.objects.filter(user=user), to_attr="_user_rating")
        return (
            Quiz.objects.filter(sessions__user=user, sessions__is_active=True)
            .select_related("creator", "folder", "folder__owner")
            .annotate(avg_rating=Avg("ratings__score"), review_count=Count("ratings", distinct=True))
            .prefetch_related(user_ratings)
            .order_by("-sessions__updated_at")
            .distinct()
        )


class SearchQuizzesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Search quizzes",
        responses={
            200: {
                "type": "object",
                "properties": {
                    "user_quizzes": {"type": "array", "items": {"type": "object"}},
                    "shared_quizzes": {"type": "array", "items": {"type": "object"}},
                    "group_quizzes": {"type": "array", "items": {"type": "object"}},
                    "public_quizzes": {"type": "array", "items": {"type": "object"}},
                },
            },
            401: OpenApiResponse(description="Unauthorized"),
            400: OpenApiResponse(description="Missing query parameter"),
        },
        parameters=[
            OpenApiParameter(
                name="query",
                required=True,
                type=str,
                location=OpenApiParameter.QUERY,
                description="Search term for quiz titles",
            )
        ],
    )
    def get(self, request):
        query = urllib.parse.unquote(request.query_params.get("query", ""))
        if not query:
            return Response({"error": "Query parameter is required"}, status=400)

        user_quizzes = Quiz.objects.filter(creator=request.user, title__icontains=query).select_related("creator")
        shared_quizzes = SharedQuiz.objects.filter(
            user=request.user, quiz__title__icontains=query, quiz__visibility__gte=1
        ).select_related("quiz__creator")
        group_quizzes = SharedQuiz.objects.filter(
            study_group__in=request.user.study_groups.all(),
            quiz__title__icontains=query,
            quiz__visibility__gte=1,
        ).select_related("quiz__creator")

        result = {
            "user_quizzes": QuizSearchResultSerializer(user_quizzes, many=True, context={"request": request}).data,
            "shared_quizzes": QuizSearchResultSerializer(
                [q.quiz for q in shared_quizzes], many=True, context={"request": request}
            ).data,
            "group_quizzes": QuizSearchResultSerializer(
                [q.quiz for q in group_quizzes], many=True, context={"request": request}
            ).data,
        }

        if request.user.account_type == AccountType.STUDENT:
            public_quizzes = Quiz.objects.filter(title__icontains=query, visibility__gte=3).select_related("creator")
            result["public_quizzes"] = QuizSearchResultSerializer(
                public_quizzes, many=True, context={"request": request}
            ).data
        else:
            result["public_quizzes"] = []

        return Response(result)


# This viewset will only return user's quizzes when listing,
#   but will allow to view all quizzes when retrieving a single quiz.
# This is by design, if the user wants to view shared quizzes,
#   they should use the SharedQuizViewSet and for public quizzes they should use the api_search_quizzes view.
# It will also allow to create, update and delete quizzes only if the user is the creator of the quiz.
@extend_schema_view(
    retrieve=extend_schema(
        parameters=[
            OpenApiParameter(
                name="include",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Comma-separated list of extra data to include. "
                "Available options: 'user_settings', 'current_session'.",
                many=True,
                style="simple",
                enum=["user_settings", "current_session"],
            )
        ]
    )
)
class QuizViewSet(viewsets.ModelViewSet):
    queryset = Quiz.objects.all()
    serializer_class = QuizSerializer
    permission_classes = [
        permissions.IsAuthenticatedOrReadOnly,
        IsQuizCreatorOrCollaboratorOrReadOnly,
        IsQuizReadable,
    ]

    def get_queryset(self):
        user = self.request.user

        if self.action == "list":
            if not user.is_authenticated:
                return Quiz.objects.none()

            return (
                Quiz.objects.filter(creator=user)
                .select_related("creator", "folder", "folder__owner")
                .annotate(avg_rating=Avg("ratings__score"), review_count=Count("ratings", distinct=True))
                .prefetch_related(
                    Prefetch("ratings", queryset=QuizRating.objects.filter(user=user), to_attr="_user_rating")
                )
            )

        queryset = Quiz.objects.all()

        if self.action in ("retrieve", "copy", "metadata", "progress", "record_answer"):
            queryset = queryset.prefetch_related(
                "questions__answers",
                "sharedquiz_set__user",
            )

        return queryset

    @extend_schema(
        summary="Get quiz metadata",
        description=(
            "Returns quiz metadata with optional preview question. Requires Api-Key header for authentication. "
        ),
        parameters=[
            OpenApiParameter(
                name="Api-Key",
                required=True,
                type=str,
                location=OpenApiParameter.HEADER,
                description="Api-Key header for authentication",
            ),
            OpenApiParameter(
                name="include",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Comma-separated list of extra data to include. Available options: 'preview_question'.",
                many=True,
                style="simple",
                enum=["preview_question"],
            ),
        ],
        responses={
            200: QuizMetaDataWithQuestionSerializer,
            403: OpenApiResponse(description="Forbidden - no access to quiz metadata"),
        },
    )
    @action(
        detail=True,
        methods=["get"],
        permission_classes=[IsInternalApiRequest],
        serializer_class=QuizMetaDataWithQuestionSerializer,
    )
    def metadata(self, request, pk=None):
        """
        Get quiz metadata for Next.js server-side rendering.

        Access Rules:
        - Private (0): Only creator
        - Shared (1): Everyone but without preview question and always anonymous
        - Unlisted/Public (≥2): Everyone

        Preview Question Rules:
        - Included only if ?include=preview_question AND visibility ≥ 2
        - Selected based on: no images (q/a), ≥3 answers
        """

        try:
            quiz = Quiz.objects.prefetch_related("questions__answers").get(pk=pk)
        except Quiz.DoesNotExist:
            raise NotFound("Quiz not found")

        user = request.user

        if not (quiz.visibility >= 1 or (user.is_authenticated and user.owns_quiz_via_folder(quiz))):
            raise PermissionDenied("You do not have permission to access this quiz metadata.")

        data = QuizMetaDataSerializer(quiz, context={"request": request}).data

        raw_includes = request.query_params.getlist("include")
        include_values = set()
        for value in raw_includes:
            if value:
                include_values.update(part.strip() for part in value.split(",") if part.strip())
        include_preview = "preview_question" in include_values

        preview_question = None
        question_count = len(quiz.questions.all())

        if include_preview and quiz.visibility >= 2:
            preview_question = get_preview_question(quiz)

        if preview_question:
            data["preview_question"] = QuestionSerializer(preview_question).data
        else:
            data["preview_question"] = None

        if quiz.visibility == 1:
            data["is_anonymous"] = True
            data["creator"] = None

        data["question_count"] = question_count

        return Response(data)

    def perform_create(self, serializer):
        serializer.save(creator=self.request.user, folder=self.request.user.root_folder)

    def perform_update(self, serializer):
        serializer.save(version=serializer.instance.version + 1)

    def perform_destroy(self, instance):
        if instance.folder.owner != self.request.user:
            raise PermissionDenied("Only the folder owner can delete this quiz")
        instance.delete()

    def get_serializer_class(self):
        action_serializers = {
            "list": QuizMetaDataSerializer,
            "metadata": QuizMetaDataWithQuestionSerializer,
            "move": MoveQuizSerializer,
        }
        return action_serializers.get(self.action, QuizSerializer)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["user"] = self.request.user
        return context

    def update(self, request, *args, **kwargs):
        quiz = self.get_object()
        if not quiz.can_edit(request.user):
            raise PermissionDenied("You do not have permission to edit this quiz")
        return super().update(request, *args, **kwargs)

    @action(
        detail=True,
        methods=["post"],
        serializer_class=MoveQuizSerializer,
        permission_classes=[permissions.IsAuthenticated, IsQuizCreator],
    )
    def move(self, request, pk=None):
        quiz = self.get_object()

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            quiz.folder_id = serializer.validated_data["folder_id"]
            quiz.save()
            return Response({"status": "Quiz moved successfully"})

        return Response(serializer.errors, status=400)

    @action(
        detail=True,
        methods=["get", "delete"],
        url_path="progress",
        permission_classes=[permissions.IsAuthenticated, IsQuizReadable],
    )
    def progress(self, request, pk=None):
        quiz = self.get_object()

        if request.method == "GET":
            session, _ = QuizSession.get_or_create_active(quiz, request.user)
            return Response(QuizSessionSerializer(session).data)

        elif request.method == "DELETE":
            # Archive current session and create new one
            with transaction.atomic():
                QuizSession.objects.filter(quiz=quiz, user=request.user, is_active=True).update(
                    is_active=False, ended_at=timezone.now()
                )
                session, _ = QuizSession.get_or_create_active(quiz, request.user)
            return Response(QuizSessionSerializer(session).data)

        raise MethodNotAllowed(request.method)

    @action(
        detail=True,
        methods=["post"],
        url_path="answer",
        permission_classes=[permissions.IsAuthenticated, IsQuizReadable],
    )
    def record_answer(self, request, pk=None):
        """Record an answer for the current session."""
        quiz = self.get_object()
        session, _ = QuizSession.get_or_create_active(quiz, request.user)

        serializer = RecordAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        question_id = serializer.validated_data["question_id"]
        if not question_id:
            return Response({"error": "question_id is required"}, status=400)

        selected_answers = serializer.validated_data["selected_answers"]

        try:
            question = Question.objects.prefetch_related("answers").get(id=question_id, quiz=quiz)
        except (Question.DoesNotExist, ValueError, TypeError, DjangoValidationError):
            return Response({"error": "Question not found in this quiz"}, status=404)

        if question.question_type == QuestionType.CLOSED:
            answers = list(question.answers.all())

            selected_ids = set(str(a) for a in selected_answers)
            valid_answer_ids = set(str(a.id) for a in answers)

            if not selected_ids.issubset(valid_answer_ids):
                return Response({"error": "One or more selected answers do not belong to this question"}, status=400)

            correct_answer_ids = set(str(a.id) for a in answers if a.is_correct)
            was_correct = correct_answer_ids == selected_ids

        elif question.question_type == QuestionType.TRUE_FALSE:
            if len(selected_answers) > 1:
                return Response({"error": "Invalid list size for this question type"}, status=400)

            if question.tf_answer is None:
                return Response({"error": "Question does not have tf answer"}, status=500)

            user_answer = selected_answers[0]  # should be True or False

            if not isinstance(user_answer, bool):
                return Response({"error": "Invalid data type"}, status=400)

            was_correct = user_answer == question.tf_answer
            selected_ids = selected_answers

        elif question.question_type == QuestionType.OPEN:
            if len(selected_answers) > 1:
                return Response({"error": "Invalid list size for this question type"}, status=400)

            input_text = selected_answers[0]

            if not isinstance(input_text, str):
                return Response({"error": "Invalid data type"}, status=400)

            correct_answer = question.answers.filter(is_correct=True).first()

            if correct_answer is None:
                return Response({"error": "Question has no correct answer"}, status=500)

            selected_ids = selected_answers

            # NOTE function normalize should be used when adding new answer to database
            was_correct = normalize(input_text) == normalize(correct_answer.text)

        else:
            return Response({"error": "Unsupported question type"}, status=400)

        record = AnswerRecord.objects.create(
            session=session,
            question=question,
            selected_answers=list(selected_ids),
            was_correct=was_correct,
        )

        update_fields = ["updated_at"]
        if "study_time" in request.data:
            try:
                study_time_seconds = float(request.data["study_time"])
            except (TypeError, ValueError):
                return Response({"error": "study_time must be a numeric value"}, status=400)
            session.study_time = timedelta(seconds=study_time_seconds)
            update_fields.append("study_time")

        if "next_question" in request.data:
            next_question_id = request.data["next_question"]
            if next_question_id is not None:
                try:
                    exists = Question.objects.filter(id=next_question_id, quiz=quiz).exists()
                except (ValueError, TypeError, DjangoValidationError):
                    return Response({"error": "next_question must be a valid question in this quiz"}, status=400)
                if not exists:
                    return Response({"error": "next_question must be a valid question in this quiz"}, status=400)
            session.current_question_id = next_question_id
            update_fields.append("current_question_id")

        session.save(update_fields=update_fields)

        return Response(AnswerRecordSerializer(record).data, status=201)

    @extend_schema(
        summary="Copy quiz to user's library",
        description=(
            "Creates a copy of the quiz. Note that `visibility`, `allow_anonymous`, "
            "and `is_anonymous` fields are NOT copied from the original quiz and "
            "will be reset to their default values."
        ),
        responses={
            201: OpenApiResponse(description="Created copy of quiz"),
            403: OpenApiResponse(description="Forbidden"),
            404: OpenApiResponse(description="Not Found"),
            429: OpenApiResponse(description="Too Many Requests"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[permissions.IsAuthenticated, IsQuizReadable],
        throttle_classes=[CopyQuizThrottle],
    )
    @transaction.atomic
    def copy(self, request, pk=None):
        original_quiz = self.get_object()

        suffix = " - kopia"
        max_length = 255
        new_title = original_quiz.title
        if len(new_title) + len(suffix) > max_length:
            new_title = new_title[: max_length - len(suffix)]
        new_title += suffix

        new_quiz = Quiz.objects.create(
            title=new_title,
            description=original_quiz.description,
            creator=request.user,
            folder=request.user.root_folder,
        )

        original_questions = list(original_quiz.questions.all())
        new_questions = []
        for q in original_questions:
            new_questions.append(
                Question(
                    id=uuid.uuid4(),
                    quiz=new_quiz,
                    order=q.order,
                    text=q.text,
                    image_url=q.image_url,
                    image_upload_id=q.image_upload_id,
                    explanation=q.explanation,
                    multiple=q.multiple,
                )
            )

        Question.objects.bulk_create(new_questions)

        new_answers = []
        for original_q, new_q in zip(original_questions, new_questions):
            for answer in original_q.answers.all():
                new_answers.append(
                    Answer(
                        question_id=new_q.id,
                        order=answer.order,
                        text=answer.text,
                        image_url=answer.image_url,
                        image_upload_id=answer.image_upload_id,
                        is_correct=answer.is_correct,
                    )
                )

        Answer.objects.bulk_create(new_answers)

        new_quiz = Quiz.objects.prefetch_related("questions__answers").get(pk=new_quiz.pk)

        return Response(
            QuizSerializer(new_quiz, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class SharedQuizViewSet(viewsets.ModelViewSet):
    queryset = SharedQuiz.objects.all()
    serializer_class = SharedQuizSerializer
    permission_classes = [permissions.IsAuthenticated, IsSharedQuizCreatorOrReadOnly]

    def get_queryset(self):
        _filter = (
            Q(user=self.request.user, quiz__visibility__gte=1)
            | Q(
                study_group__in=self.request.user.study_groups.all(),
                quiz__visibility__gte=1,
            )
            | Q(quiz__creator=self.request.user)
            | Q(quiz__folder__owner=self.request.user)
        )
        if self.request.query_params.get("quiz"):
            _filter &= Q(quiz_id=self.request.query_params.get("quiz"))
        return SharedQuiz.objects.filter(_filter)

    def perform_create(self, serializer):
        shared_quiz = serializer.save()

        def send_notification():
            if shared_quiz.user:
                notify_quiz_shared_to_users(shared_quiz.quiz, shared_quiz.user)
            elif shared_quiz.study_group:
                notify_quiz_shared_to_groups(shared_quiz.quiz, shared_quiz.study_group)

        transaction.on_commit(send_notification)

    def perform_destroy(self, instance):
        instance.delete()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"user": self.request.user})
        return context


class ReportQuestionIssueView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Report a quiz question issue",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "quiz_id": {"type": "string", "format": "uuid"},
                    "question_id": {"type": "string"},
                    "issue": {"type": "string"},
                },
                "required": ["quiz_id", "question_id", "issue"],
            }
        },
        responses={
            201: OpenApiResponse(description="Issue reported successfully"),
            400: OpenApiResponse(description="Missing or invalid data"),
            401: OpenApiResponse(description="Unauthorized"),
            404: OpenApiResponse(description="Quiz not found"),
            500: OpenApiResponse(description="Email sending failed"),
        },
    )
    def post(self, request):
        data = request.data
        if not data.get("quiz_id") or not data.get("question_id") or not data.get("issue"):
            return Response({"error": "Missing data"}, status=400)

        quiz = Quiz.objects.get(id=data.get("quiz_id"))
        if not quiz:
            return Response({"error": "Quiz not found"}, status=404)

        if request.user == quiz.creator:
            return Response(
                {"error": "You cannot report issues with your own questions"},
                status=400,
            )

        try:
            question = Question.objects.get(id=data.get("question_id"), quiz=quiz)
        except Question.DoesNotExist:
            return Response({"error": "Question not found"}, status=404)

        subject = "Zgłoszenie błędu w pytaniu"
        query_params = urllib.parse.urlencode({"scroll_to": f"question-{question.id}"})
        cta_url = f"{settings.FRONTEND_URL}/edit-quiz/{quiz.id}/?{query_params}"

        content = (
            f"{escape(request.user.full_name)} zgłosił błąd w pytaniu "
            f'"{escape(question.text)}" quizu {escape(quiz.title)}.\n\n'
            f"{escape(data.get('issue'))}"
        )

        recipient_list = [quiz.creator.email]
        reply_to = [request.user.email]

        try:
            send_email(
                subject=subject,
                recipient_list=recipient_list,
                title="Zgłoszenie błędu w pytaniu",
                content=content,
                cta_url=cta_url,
                cta_text="Przejdź do edycji",
                reply_to=reply_to,
                fail_silently=False,
            )
        except Exception as e:
            logger.exception("Email sending failed: %s", str(e))
            return Response({"error": "Email sending failed"}, status=500)

        return Response({"status": "ok"}, status=201)


class QuestionViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = QuestionSerializer
    queryset = Question.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsQuizCreatorOrCollaboratorOrReadOnly, IsQuestionReadable]

    @extend_schema(
        responses={
            200: OpenApiResponse(
                description="Question deleted successfully",
                response={
                    "type": "object",
                    "properties": {
                        "current_question": {
                            "type": "integer",
                            "format": "uuid",
                            "nullable": True,
                            "description": "ID of the new current question",
                            "example": "123e4567-e89b-12d3-a456-426614174000",
                        },
                    },
                },
            )
        }
    )
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        affected_sessions = QuizSession.objects.filter(current_question=instance, is_active=True)
        new_question = None

        if affected_sessions.exists():
            new_question = instance.quiz.questions.exclude(id=instance.id).order_by("?").first()
            affected_sessions.update(current_question=new_question)

        instance.delete()

        return Response({"current_question": new_question.id if new_question else None}, status=status.HTTP_200_OK)


class FolderViewSet(viewsets.ModelViewSet):
    serializer_class = FolderSerializer
    queryset = Folder.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsFolderOwner]

    def get_queryset(self):
        return Folder.objects.filter(owner=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        if not serializer.validated_data.get("parent"):
            serializer.save(owner=self.request.user, parent=self.request.user.root_folder)
        else:
            serializer.save(owner=self.request.user)

    def perform_destroy(self, instance):
        if hasattr(instance, "root_owner"):
            raise PermissionDenied("Cannot delete root folder.")
        instance.delete()

    @action(detail=True, methods=["post"], serializer_class=MoveFolderSerializer)
    def move(self, request, pk=None):
        folder = self.get_object()

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            folder.parent_id = serializer.validated_data["parent_id"]
            folder.save()
            return Response({"status": "Folder moved successfully"})

        return Response(serializer.errors, status=400)


class QuizRatingViewSet(viewsets.ModelViewSet):
    """
    Manages quiz ratings for the authenticated user.
    A user can only have one rating per quiz (enforced by unique constraint).
    Users can only rate quizzes they have read access to.
    """

    permission_classes = [permissions.IsAuthenticated, IsRatingUserOrReadOnly]
    serializer_class = QuizRatingSerializer
    queryset = QuizRating.objects.all()
    filterset_fields = ["quiz"]
    ordering_fields = ["created_at", "updated_at", "score"]
    ordering = ["-created_at"]

    def _accessible_quizzes_filter(self, user):
        shared_quiz_ids = SharedQuiz.objects.filter(
            Q(user=user) | Q(study_group__in=user.study_groups.all()), quiz__visibility__gte=1
        ).values_list("quiz_id", flat=True)
        return Q(quiz__folder__owner=user) | Q(quiz_id__in=shared_quiz_ids) | Q(quiz__visibility__gte=2)

    def get_queryset(self):
        user = self.request.user
        return (
            QuizRating.objects.filter(self._accessible_quizzes_filter(user)).select_related("quiz", "user").distinct()
        )

    def list(self, request, *args, **kwargs):
        if "quiz" not in request.query_params:
            raise ValidationError({"quiz": "This query parameter is required when listing ratings."})
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        queryset = self.filter_queryset(self.get_queryset().filter(user=request.user))
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def perform_create(self, serializer):
        quiz = serializer.validated_data["quiz"]
        if not user_has_quiz_read_access(self.request.user, quiz):
            raise PermissionDenied("You do not have access to this quiz.")
        serializer.save()


class CommentViewSet(viewsets.ModelViewSet):
    """
    Manages comments on quizzes.

    Access control:
      - List requires ?quiz= query param; returns comments only for quizzes
        the user can read (owner, shared, or public).
      - Create validates quiz read access.
      - Only the author can modify or delete their own comments.

    DELETE performs a soft delete — the record is kept but content/author are
    hidden in responses for deleted comments to preserve thread structure.
    """

    permission_classes = [permissions.IsAuthenticated, IsCommentAuthorOrReadOnly]
    serializer_class = CommentSerializer
    queryset = Comment.objects.all()
    filterset_fields = ["quiz"]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]

    def _accessible_quizzes_filter(self, user):
        shared_quiz_ids = SharedQuiz.objects.filter(
            Q(user=user) | Q(study_group__in=user.study_groups.all()), quiz__visibility__gte=1
        ).values_list("quiz_id", flat=True)
        return Q(quiz__folder__owner=user) | Q(quiz_id__in=shared_quiz_ids) | Q(quiz__visibility__gte=2)

    def get_queryset(self):
        user = self.request.user
        return (
            Comment.objects.filter(self._accessible_quizzes_filter(user)).select_related("author", "parent").distinct()
        )

    def list(self, request, *args, **kwargs):
        if "quiz" not in request.query_params:
            raise ValidationError({"quiz": "This query parameter is required when listing comments."})
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        queryset = self.filter_queryset(self.get_queryset().filter(author=request.user))
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def perform_create(self, serializer):
        quiz = serializer.validated_data["quiz"]
        if not user_has_quiz_read_access(self.request.user, quiz):
            raise PermissionDenied("You do not have access to this quiz.")
        serializer.save(author=self.request.user)

    def perform_destroy(self, instance: Comment):
        if instance.is_deleted:
            raise ValidationError("Comment is already deleted.")

        instance.mark_as_deleted()


class LibraryView(APIView):
    permission_classes = [IsAuthenticated]

    def _access_predicate(self, user):
        return Q(owner=user) | Q(shares__user=user) | Q(shares__study_group__in=user.study_groups.all())

    def _has_access(self, user, folder_id):
        # Precompute IDs of all folders the user can directly access.
        accessible_folder_ids = set(Folder.objects.filter(self._access_predicate(user)).values_list("id", flat=True))

        # Direct access to this folder.
        if folder_id in accessible_folder_ids:
            return True

        # Walk up the ancestor chain using lightweight queries and check access in-memory.
        folder = Folder.objects.filter(id=folder_id).only("id", "parent_id").first()
        if not folder:
            return False

        current_parent_id = folder.parent_id
        while current_parent_id:
            if current_parent_id in accessible_folder_ids:
                return True
            parent = Folder.objects.filter(id=current_parent_id).only("id", "parent_id").first()
            if not parent:
                break
            current_parent_id = parent.parent_id
        return False

    def _get_subfolders(self, user, folder_id):
        return Folder.objects.filter(parent_id=folder_id).distinct().order_by("-created_at")

    def _get_quizzes(self, user, folder_id):
        return Quiz.objects.filter(folder_id=folder_id).distinct().order_by("-created_at")

    def _build_breadcrumbs(self, user, folder_id):
        try:
            folder = Folder.objects.get(id=folder_id)
        except Folder.DoesNotExist:
            return []

        chain = []
        current = folder
        while current:
            chain.append(current)
            current = current.parent

        chain.reverse()

        accessible_ids = set(
            Folder.objects.filter(
                self._access_predicate(user),
                id__in=[f.id for f in chain],
            ).values_list("id", flat=True)
        )

        for i, f in enumerate(chain):
            if f.id in accessible_ids:
                return [{"id": str(entry.id), "name": entry.name} for entry in chain[i:]]

        return []

    @extend_schema(
        summary="List library contents",
        parameters=[
            OpenApiParameter(
                name="folder_id",
                type=str,
                location=OpenApiParameter.PATH,
                required=False,
                description="UUID of the folder to browse. Defaults to the user's root folder.",
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="Folder contents with breadcrumb path",
                response={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string", "format": "uuid"},
                                    "name": {"type": "string"},
                                },
                            },
                            "description": "Breadcrumb path from the topmost accessible folder to the current folder.",
                        },
                        "items": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "List of folders and quizzes in the current folder.",
                        },
                    },
                },
            ),
            403: OpenApiResponse(description="No permission to access this folder"),
        },
    )
    def get(self, request, folder_id=None):
        user = request.user

        if folder_id is None:
            folder_id = user.root_folder_id

        if not self._has_access(user, folder_id):
            return Response(
                {"error": "You do not have permission to access this folder"}, status=status.HTTP_403_FORBIDDEN
            )

        items = list(self._get_subfolders(user, folder_id)) + list(self._get_quizzes(user, folder_id))
        return Response(
            {
                "path": self._build_breadcrumbs(user, folder_id),
                "items": LibraryItemSerializer(items, many=True, context={"request": request}).data,
            }
        )
