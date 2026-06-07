import urllib.parse
import uuid

from django.db import transaction
from django.db.models import Avg, Count, Prefetch, Q
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    AuthenticationFailed,
    MethodNotAllowed,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from quizzes.models import (
    Answer,
    Comment,
    Folder,
    FolderType,
    Question,
    QuestionChangeSuggestion,
    Quiz,
    QuizRating,
    QuizSession,
    SharedQuiz,
)
from quizzes.permissions import (
    IsCommentAuthorOrReadOnly,
    IsFolderOwner,
    IsQuestionReadable,
    IsQuizCreator,
    IsQuizCreatorOrCollaboratorOrReadOnly,
    IsQuizReadable,
    IsRatingUserOrReadOnly,
    IsSharedQuizCreatorOrReadOnly,
    accessible_quizzes_q,
    is_internal_api_request,
    user_has_quiz_read_access,
)
from quizzes.serializers import (
    AnswerRecordSerializer,
    AnswerSerializer,
    BulkCreateQuestionsSerializer,
    CommentSerializer,
    FolderSerializer,
    LibraryItemSerializer,
    MoveFolderSerializer,
    MoveQuizSerializer,
    QuestionChangeSuggestionSerializer,
    QuestionSerializer,
    QuizMetaDataSerializer,
    QuizMetaDataWithQuestionSerializer,
    QuizRatingSerializer,
    QuizSearchResultSerializer,
    QuizSerializer,
    QuizSessionSerializer,
    QuizStatsSerializer,
    RecordAnswerSerializer,
    SharedQuizSerializer,
)
from quizzes.services.metadata import get_preview_question
from quizzes.services.notifications import (
    notify_question_comment_created,
    notify_quiz_shared_to_groups,
    notify_quiz_shared_to_users,
)
from quizzes.services.operations import (
    UNSET,
    QuizOperationError,
    get_random_recent_question,
    grouped_search_quizzes,
    record_quiz_answer,
    reset_readable_session,
)
from quizzes.services.stats import (
    get_quiz_hardest_questions,
    get_quiz_hourly_stats,
    get_quiz_sessions_stats,
    get_quiz_stats,
    get_quiz_timeline_stats,
)
from quizzes.services.suggestions import (
    SuggestionApplyError,
    SuggestionVersionConflict,
    apply_question_change_suggestion,
    reject_question_change_suggestion,
)
from quizzes.throttling import CopyQuizThrottle, QuizStatsThrottle
from quizzes.utils import parse_include_values, parse_positive_int_query_param
from users.models import AccountType

ALLOWED_STATS_SCOPES = {"me", "all"}


def resolve_stats_scope_user(request, quiz):
    scope = request.query_params.get("scope", "me")
    if scope not in ALLOWED_STATS_SCOPES:
        raise ValidationError({"scope": "Invalid value. Allowed values are: me, all."})

    if scope == "all":
        if not quiz.can_edit(request.user):
            raise PermissionDenied("You do not have permission to view global statistics for this quiz.")
        return None

    return request.user


def resolve_session_stats_user(request):
    scope = request.query_params.get("scope", "me")
    if scope != "me":
        raise ValidationError({"scope": "Invalid value. Sessions statistics only support scope=me."})

    return request.user


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
        try:
            random_question = get_random_recent_question(request.user)
        except QuizOperationError as exc:
            return Response({"error": exc.message}, status=exc.status_code)

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
            .annotate(
                questions_count=Count("questions", distinct=True),
                avg_rating=Avg("ratings__score"),
                review_count=Count("ratings", distinct=True),
            )
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

        grouped_quizzes = grouped_search_quizzes(
            request.user,
            query,
            include_public=request.user.account_type == AccountType.STUDENT,
        )
        result = {
            "user_quizzes": QuizSearchResultSerializer(
                grouped_quizzes["user_quizzes"], many=True, context={"request": request}
            ).data,
            "shared_quizzes": QuizSearchResultSerializer(
                grouped_quizzes["shared_quizzes"], many=True, context={"request": request}
            ).data,
            "group_quizzes": QuizSearchResultSerializer(
                grouped_quizzes["group_quizzes"], many=True, context={"request": request}
            ).data,
            "public_quizzes": QuizSearchResultSerializer(
                grouped_quizzes["public_quizzes"], many=True, context={"request": request}
            ).data,
        }

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
                .annotate(
                    questions_count=Count("questions", distinct=True),
                    avg_rating=Avg("ratings__score"),
                    review_count=Count("ratings", distinct=True),
                )
                .prefetch_related(
                    Prefetch("ratings", queryset=QuizRating.objects.filter(user=user), to_attr="_user_rating")
                )
            )

        queryset = Quiz.objects.all()

        if self.action in ("retrieve", "copy", "metadata", "progress", "record_answer"):
            queryset = queryset.select_related("creator", "folder", "folder__owner").prefetch_related(
                Prefetch("questions", queryset=Question.objects.select_related("image_upload")),
                Prefetch(
                    "questions__answers",
                    queryset=Answer.objects.select_related("image_upload"),
                ),
                "sharedquiz_set__user",
            )

        return queryset

    @extend_schema(
        summary="Get quiz metadata",
        description=(
            "Returns quiz metadata with optional preview question. "
            "Requests with a valid Api-Key use internal server-side access rules. "
            "Requests without Api-Key use normal quiz read permissions."
        ),
        parameters=[
            OpenApiParameter(
                name="Api-Key",
                required=False,
                type=str,
                location=OpenApiParameter.HEADER,
                description="Optional internal Api-Key header for server-to-server access",
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
        permission_classes=[permissions.AllowAny],
        serializer_class=QuizMetaDataWithQuestionSerializer,
    )
    def metadata(self, request, pk=None):
        """
        Get quiz metadata for Next.js server-side rendering.

        Access Rules:
        - Private (0): Only creator
        - Shared (1): Everyone but without preview question and always anonymous
        - Unlisted/Public (â‰Ą2): Everyone

        Preview Question Rules:
        - Included only if ?include=preview_question AND visibility â‰Ą 2
        - Selected based on: no images (q/a), â‰Ą3 answers
        """

        try:
            quiz = (
                Quiz.objects.prefetch_related("questions__answers")
                .annotate(questions_count=Count("questions", distinct=True))
                .get(pk=pk)
            )
        except Quiz.DoesNotExist:
            raise NotFound("Quiz not found")

        api_key = request.headers.get("Api-Key")
        has_internal_access = is_internal_api_request(request)
        if api_key and not has_internal_access:
            raise AuthenticationFailed("Invalid Api-Key.")

        user = request.user

        if has_internal_access:
            if not (quiz.visibility >= 1 or (user.is_authenticated and user.owns_quiz_via_folder(quiz))):
                raise PermissionDenied("You do not have permission to access this quiz metadata.")
        elif not user_has_quiz_read_access(user, quiz):
            raise PermissionDenied("You do not have permission to access this quiz metadata.")

        data = QuizMetaDataSerializer(quiz, context={"request": request}).data

        include_values = parse_include_values(request)
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

        if instance.folder.folder_type != FolderType.ARCHIVE:
            archive_folder, _ = Folder.objects.get_or_create(
                owner=self.request.user,
                folder_type=FolderType.ARCHIVE,
                defaults={"name": Folder.DEFAULT_ARCHIVE_NAME, "parent": self.request.user.root_folder},
            )
            instance.folder = archive_folder
            instance.archived_at = timezone.now()
            instance.save(update_fields=["folder", "archived_at", "updated_at"])
        else:
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
            new_folder_id = serializer.validated_data["folder_id"]
            destination = Folder.objects.get(pk=new_folder_id)
            quiz.folder_id = new_folder_id
            quiz.archived_at = timezone.now() if destination.folder_type == FolderType.ARCHIVE else None
            quiz.save(update_fields=["folder_id", "archived_at", "updated_at"])
            return Response({"status": "Quiz moved successfully"})

        return Response(serializer.errors, status=400)

    @action(
        detail=True,
        methods=["post"],
        url_path="move-to-archive",
        permission_classes=[permissions.IsAuthenticated, IsQuizCreator],
    )
    def move_to_archive(self, request, pk=None):
        quiz = self.get_object()

        if quiz.folder.folder_type == FolderType.ARCHIVE:
            return Response({"status": "Quiz already in archive"}, status=status.HTTP_200_OK)

        archive_folder, _ = Folder.objects.get_or_create(
            owner=request.user,
            folder_type=FolderType.ARCHIVE,
            defaults={"name": Folder.DEFAULT_ARCHIVE_NAME, "parent": request.user.root_folder},
        )

        quiz.folder = archive_folder
        quiz.archived_at = timezone.now()
        quiz.save(update_fields=["folder", "archived_at", "updated_at"])
        return Response({"status": "Quiz moved successfully"}, status=status.HTTP_200_OK)

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
            state = reset_readable_session(request.user, quiz.id)
            return Response(QuizSessionSerializer(state.session).data)

        raise MethodNotAllowed(request.method)

    @extend_schema(
        summary="Get quiz statistics",
        description=(
            "Returns aggregated quiz statistics. "
            "By default (`scope=me`) it returns data for the authenticated user across their sessions. "
            "Use `scope=all` to aggregate data across all users, available only to quiz editors. "
            "`study_time_seconds` reflects active session time only for `scope=me`; "
            "for `scope=all` this field is `null` (use total/average fields instead). "
            "Pass `?include=per_question` to include a per-question breakdown."
        ),
        parameters=[
            OpenApiParameter(
                name="scope",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Stats scope. Use 'me' for current user, 'all' for all users (quiz editors only).",
                enum=["me", "all"],
            ),
            OpenApiParameter(
                name="include",
                type=str,
                location=OpenApiParameter.QUERY,
                description=(
                    "Extra data to include. Accepts CSV (`?include=per_question`) "
                    "or repeated params (`?include=a&include=b`). "
                    "Available options: 'per_question'."
                ),
                many=True,
                explode=False,
                enum=["per_question"],
            ),
        ],
        responses={
            200: QuizStatsSerializer,
            400: OpenApiResponse(description="Bad request - invalid query parameters"),
            401: OpenApiResponse(description="Unauthorized - authentication required"),
            403: OpenApiResponse(description="Forbidden - no read access to this quiz"),
            404: OpenApiResponse(description="Quiz not found"),
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="stats",
        permission_classes=[permissions.IsAuthenticated, IsQuizReadable],
        throttle_classes=[QuizStatsThrottle],
    )
    def stats(self, request, pk=None):
        """Return aggregated statistics for the current user and this quiz."""
        quiz = self.get_object()

        include_values = parse_include_values(request)
        include_per_question = "per_question" in include_values

        user = resolve_stats_scope_user(request, quiz)

        data = get_quiz_stats(quiz, user, include_per_question=include_per_question)
        serializer = QuizStatsSerializer(instance=data)
        return Response(serializer.data)

    @extend_schema(
        summary="Get quiz timeline statistics",
        description=(
            "Per-day breakdown over the last `days` days (default 30, max 365). "
            "Each entry contains `sessions_count`, `total_answers`, `correct_answers`, "
            "and `total_study_time_seconds` for that calendar day. "
            "Use `scope=all` to aggregate across all users (quiz editors only)."
        ),
        parameters=[
            OpenApiParameter(
                name="scope",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Stats scope. Use 'me' for current user, 'all' for all users (quiz editors only).",
                enum=["me", "all"],
            ),
            OpenApiParameter(
                name="days",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Number of trailing days to include in the timeline (1-365, default 30).",
            ),
        ],
        responses={
            200: OpenApiResponse(description="Timeline statistics"),
            400: OpenApiResponse(description="Bad request - invalid query parameters"),
            401: OpenApiResponse(description="Unauthorized - authentication required"),
            403: OpenApiResponse(description="Forbidden - no read access to this quiz"),
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="stats/timeline",
        permission_classes=[permissions.IsAuthenticated, IsQuizReadable],
        throttle_classes=[QuizStatsThrottle],
    )
    def stats_timeline(self, request, pk=None):
        """Return timeline statistics (last N days, default 30)."""
        quiz = self.get_object()
        user = resolve_stats_scope_user(request, quiz)
        days = parse_positive_int_query_param(request, "days", default=30, max_value=365)

        data = get_quiz_timeline_stats(quiz, user=user, days=days)
        return Response(data)

    @extend_schema(
        summary="Get per-session statistics",
        description=(
            "Returns one entry per quiz session within the last `days` days "
            "(default 30, max 365), in chronological order. Each entry is a single "
            "data point for line charts of score-over-time and study-time-over-time. "
            "This endpoint only returns sessions for the authenticated user."
        ),
        parameters=[
            OpenApiParameter(
                name="scope",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Stats scope. Only 'me' is supported for this endpoint.",
                enum=["me"],
            ),
            OpenApiParameter(
                name="days",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Number of trailing days to include (1-365, default 30).",
            ),
        ],
        responses={
            200: OpenApiResponse(description="Per-session statistics"),
            400: OpenApiResponse(description="Bad request - invalid query parameters"),
            401: OpenApiResponse(description="Unauthorized - authentication required"),
            403: OpenApiResponse(description="Forbidden - no read access to this quiz"),
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="stats/sessions",
        permission_classes=[permissions.IsAuthenticated, IsQuizReadable],
        throttle_classes=[QuizStatsThrottle],
    )
    def stats_sessions(self, request, pk=None):
        """Return per-session data points for score / study-time line charts."""
        quiz = self.get_object()
        user = resolve_session_stats_user(request)
        days = parse_positive_int_query_param(request, "days", default=30, max_value=365)

        data = get_quiz_sessions_stats(quiz, user=user, days=days)
        return Response(data)

    @extend_schema(
        summary="Get hardest questions",
        description=(
            "Top N questions by wrong-answer count (default 10, max 100). "
            "Each entry includes `question_id`, `question_text`, `wrong_answers`, and `total_answers`. "
            "Use `scope=all` to aggregate across all users (quiz editors only)."
        ),
        parameters=[
            OpenApiParameter(
                name="scope",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Stats scope. Use 'me' for current user, 'all' for all users (quiz editors only).",
                enum=["me", "all"],
            ),
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Number of hardest questions to return (1-100, default 10).",
            ),
        ],
        responses={
            200: OpenApiResponse(description="Hardest questions statistics"),
            400: OpenApiResponse(description="Bad request - invalid query parameters"),
            401: OpenApiResponse(description="Unauthorized - authentication required"),
            403: OpenApiResponse(description="Forbidden - no read access to this quiz"),
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="stats/hardest-questions",
        permission_classes=[permissions.IsAuthenticated, IsQuizReadable],
        throttle_classes=[QuizStatsThrottle],
    )
    def stats_hardest_questions(self, request, pk=None):
        """Return top N hardest questions (default 10)."""
        quiz = self.get_object()
        user = resolve_stats_scope_user(request, quiz)
        limit = parse_positive_int_query_param(request, "limit", default=10, max_value=100)

        data = get_quiz_hardest_questions(quiz, user=user, limit=limit)
        return Response(data)

    @extend_schema(
        summary="Get hourly activity statistics",
        description=(
            "Number of sessions started per hour-of-day (0-23) in the database timezone. "
            "Always returns 24 entries; missing hours are filled with 0. "
            "Use `scope=all` to aggregate across all users (quiz editors only)."
        ),
        parameters=[
            OpenApiParameter(
                name="scope",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Stats scope. Use 'me' for current user, 'all' for all users (quiz editors only).",
                enum=["me", "all"],
            )
        ],
        responses={
            200: OpenApiResponse(description="Hourly statistics"),
            400: OpenApiResponse(description="Bad request - invalid query parameters"),
            401: OpenApiResponse(description="Unauthorized - authentication required"),
            403: OpenApiResponse(description="Forbidden - no read access to this quiz"),
        },
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="stats/hourly",
        permission_classes=[permissions.IsAuthenticated, IsQuizReadable],
        throttle_classes=[QuizStatsThrottle],
    )
    def stats_hourly(self, request, pk=None):
        """Return radar chart data (activity grouped by hour)."""
        quiz = self.get_object()
        user = resolve_stats_scope_user(request, quiz)

        data = get_quiz_hourly_stats(quiz, user=user)
        return Response(data)

    @action(
        detail=True,
        methods=["post"],
        url_path="answer",
        permission_classes=[permissions.IsAuthenticated, IsQuizReadable],
    )
    def record_answer(self, request, pk=None):
        """Record an answer for the current session."""
        quiz = self.get_object()

        serializer = RecordAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        question_id = serializer.validated_data["question_id"]
        if not question_id:
            return Response({"error": "question_id is required"}, status=400)

        selected_answers = serializer.validated_data["selected_answers"]
        next_question_id = request.data.get("next_question", UNSET)
        try:
            result = record_quiz_answer(
                request.user,
                quiz.id,
                question_id,
                selected_answers,
                study_time=request.data.get("study_time") if "study_time" in request.data else None,
                next_question_id=next_question_id,
            )
        except QuizOperationError as exc:
            return Response({"error": exc.message}, status=exc.status_code)

        return Response(AnswerRecordSerializer(result.record).data, status=201)

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
        return SharedQuiz.objects.filter(_filter).prefetch_related(
            Prefetch(
                "quiz",
                queryset=Quiz.objects.annotate(questions_count=Count("questions", distinct=True)).select_related(
                    "creator", "folder", "folder__owner"
                ),
            )
        )

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

        try:
            quiz = Quiz.objects.get(id=data.get("quiz_id"))
        except (Quiz.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Quiz not found"}, status=404)

        if not user_has_quiz_read_access(request.user, quiz):
            raise PermissionDenied("You do not have access to this quiz.")

        if request.user == quiz.creator:
            return Response(
                {"error": "You cannot report issues with your own questions"},
                status=400,
            )

        try:
            question = Question.objects.get(id=data.get("question_id"), quiz=quiz)
        except Question.DoesNotExist:
            return Response({"error": "Question not found"}, status=404)

        serializer_data = {
            "quiz": quiz.id,
            "question": question.id,
            "content": data.get("issue"),
        }
        if data.get("suggestion"):
            serializer_data["suggestion"] = data["suggestion"]

        serializer = CommentSerializer(data=serializer_data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(author=request.user)

        transaction.on_commit(lambda: notify_question_comment_created(comment))

        return Response(CommentSerializer(comment, context={"request": request}).data, status=201)


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
        request=BulkCreateQuestionsSerializer,
        responses={201: QuestionSerializer(many=True)},
    )
    @action(detail=False, methods=["post"], url_path="bulk-create")
    def bulk_create(self, request):
        serializer = BulkCreateQuestionsSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        questions = serializer.save()
        return Response(
            QuestionSerializer(questions, many=True, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

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
        if instance.folder_type == FolderType.ARCHIVE:
            raise PermissionDenied("Cannot delete archive folder.")
        instance.delete()

    @action(detail=True, methods=["post"], serializer_class=MoveFolderSerializer)
    def move(self, request, pk=None):
        folder = self.get_object()

        if folder.folder_type == FolderType.ARCHIVE:
            return Response({"error": "Cannot move archive folder."}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            folder.parent_id = serializer.validated_data["parent_id"]
            folder.save()
            return Response({"status": "Folder moved successfully"}, status=status.HTTP_200_OK)

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

    def get_queryset(self):
        user = self.request.user
        return QuizRating.objects.filter(accessible_quizzes_q(user)).select_related("quiz", "user").distinct()

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
        serializer.save(user=self.request.user)


class CommentViewSet(viewsets.ModelViewSet):
    """
    Manages comments on quizzes.

    Access control:
      - List requires ?quiz= query param; returns comments only for quizzes
        the user can read (owner, shared, or public).
      - Create validates quiz read access.
      - Only the author can modify or delete their own comments.

    DELETE performs a soft delete the record is kept but content/author are
    hidden in responses for deleted comments to preserve thread structure.
    """

    permission_classes = [permissions.IsAuthenticated, IsCommentAuthorOrReadOnly]
    serializer_class = CommentSerializer
    queryset = Comment.objects.all()
    filterset_fields = ["quiz"]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]

    def get_permissions(self):
        if self.action in {"accept_suggestion", "reject_suggestion"}:
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        return (
            Comment.objects.filter(accessible_quizzes_q(user))
            .select_related("author", "parent", "quiz", "quiz__folder", "question")
            .prefetch_related("suggestion")
            .distinct()
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
        comment = serializer.save(author=self.request.user)
        transaction.on_commit(lambda: notify_question_comment_created(comment))

    def perform_destroy(self, instance: Comment):
        if instance.is_deleted:
            raise ValidationError("Comment is already deleted.")

        instance.mark_as_deleted()

    @action(detail=True, methods=["post"], url_path="accept-suggestion")
    def accept_suggestion(self, request, pk=None):
        comment = self.get_object()

        if not comment.quiz.can_edit(request.user):
            raise PermissionDenied("You do not have permission to accept suggestions for this quiz.")

        try:
            suggestion = comment.suggestion
        except QuestionChangeSuggestion.DoesNotExist:
            raise ValidationError({"suggestion": "This comment has no suggestion."})

        force = request.data.get("force", False)
        if isinstance(force, str):
            force = force.lower() in {"1", "true", "yes"}
        try:
            suggestion = apply_question_change_suggestion(suggestion, request.user, force=force)
        except SuggestionVersionConflict as exc:
            return Response({"error": str(exc)}, status=status.HTTP_409_CONFLICT)
        except SuggestionApplyError as exc:
            raise ValidationError({"suggestion": str(exc)})

        return Response(QuestionChangeSuggestionSerializer(suggestion, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="reject-suggestion")
    def reject_suggestion(self, request, pk=None):
        comment = self.get_object()

        if not comment.quiz.can_edit(request.user):
            raise PermissionDenied("You do not have permission to reject suggestions for this quiz.")

        try:
            suggestion = comment.suggestion
        except QuestionChangeSuggestion.DoesNotExist:
            raise ValidationError({"suggestion": "This comment has no suggestion."})

        try:
            suggestion = reject_question_change_suggestion(suggestion, request.user)
        except SuggestionApplyError as exc:
            raise ValidationError({"suggestion": str(exc)})

        return Response(QuestionChangeSuggestionSerializer(suggestion, context={"request": request}).data)


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
