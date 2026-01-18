import random
import urllib.parse
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.html import escape
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from quizzes.models import (
    Answer,
    AnswerRecord,
    Folder,
    Question,
    Quiz,
    QuizSession,
    SharedQuiz,
)
from quizzes.permissions import (
    IsFolderOwner,
    IsQuizMaintainer,
    IsQuizMaintainerOrCollaborator,
    IsSharedQuizMaintainerOrReadOnly,
)
from quizzes.serializers import (
    AnswerRecordSerializer,
    AnswerSerializer,
    FolderSerializer,
    MoveFolderSerializer,
    MoveQuizSerializer,
    QuizMetaDataSerializer,
    QuizSearchResultSerializer,
    QuizSerializer,
    QuizSessionSerializer,
    SharedQuizSerializer,
)
from quizzes.services.notifications import (
    notify_quiz_shared_to_groups,
    notify_quiz_shared_to_users,
)
from quizzes.throttling import CopyQuizThrottle
from testownik_core.emails import send_email


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


class LastUsedQuizzesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get recently used quizzes",
        responses={
            200: QuizMetaDataSerializer(many=True),
            401: OpenApiResponse(description="Unauthorized"),
        },
        parameters=[
            OpenApiParameter(
                name="limit",
                required=False,
                type=int,
                location=OpenApiParameter.QUERY,
                description="Maximum number of recent quizzes to return (max: 20)",
            )
        ],
    )
    def get(self, request):
        try:
            max_quizzes_count = min(int(request.query_params.get("limit", 4)), 20)
        except (ValueError, TypeError):
            max_quizzes_count = 4

        sessions = (
            QuizSession.objects.filter(user=request.user, is_active=True)
            .select_related("quiz", "quiz__maintainer")
            .order_by("-started_at")[:max_quizzes_count]
        )
        last_used_quizzes = [session.quiz for session in sessions]

        serializer = QuizMetaDataSerializer(last_used_quizzes, many=True, context={"request": request})
        return Response(serializer.data)


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

        user_quizzes = Quiz.objects.filter(maintainer=request.user, title__icontains=query).select_related("maintainer")
        shared_quizzes = SharedQuiz.objects.filter(
            user=request.user, quiz__title__icontains=query, quiz__visibility__gte=1
        ).select_related("quiz__maintainer")
        group_quizzes = SharedQuiz.objects.filter(
            study_group__in=request.user.study_groups.all(),
            quiz__title__icontains=query,
            quiz__visibility__gte=1,
        ).select_related("quiz__maintainer")
        public_quizzes = Quiz.objects.filter(title__icontains=query, visibility__gte=3).select_related("maintainer")

        return Response(
            {
                "user_quizzes": QuizSearchResultSerializer(user_quizzes, many=True, context={"request": request}).data,
                "shared_quizzes": QuizSearchResultSerializer(
                    [q.quiz for q in shared_quizzes], many=True, context={"request": request}
                ).data,
                "group_quizzes": QuizSearchResultSerializer(
                    [q.quiz for q in group_quizzes], many=True, context={"request": request}
                ).data,
                "public_quizzes": QuizSearchResultSerializer(
                    public_quizzes, many=True, context={"request": request}
                ).data,
            }
        )


# This viewset will only return user's quizzes when listing,
#   but will allow to view all quizzes when retrieving a single quiz.
# This is by design, if the user wants to view shared quizzes,
#   they should use the SharedQuizViewSet and for public quizzes they should use the api_search_quizzes view.
# It will also allow to create, update and delete quizzes only if the user is the maintainer of the quiz.
class QuizViewSet(viewsets.ModelViewSet):
    queryset = Quiz.objects.all()
    serializer_class = QuizSerializer
    permission_classes = [
        permissions.IsAuthenticatedOrReadOnly,
        IsQuizMaintainerOrCollaborator,
    ]

    def get_queryset(self):
        user = self.request.user

        if not user.is_authenticated:
            if self.action == "list":
                return Quiz.objects.none()
            return Quiz.objects.filter(visibility__gte=2, allow_anonymous=True)

        qs = Q(maintainer=user)

        if self.action in ("retrieve", "update", "partial_update", "progress", "record_answer", "copy"):
            qs |= Q(visibility__gte=2)  # Public/unlisted
            qs |= Q(visibility__gte=1, sharedquiz__user=user)
            qs |= Q(visibility__gte=1, sharedquiz__study_group__in=user.study_groups.all())

        queryset = Quiz.objects.filter(qs).distinct()

        if self.action in ("retrieve", "copy"):
            queryset = queryset.prefetch_related(
                "questions__answers",
                "sharedquiz_set__user",
            )

        return queryset

    def perform_create(self, serializer):
        serializer.save(maintainer=self.request.user)

    def perform_update(self, serializer):
        serializer.save(version=serializer.instance.version + 1)

    def perform_destroy(self, instance):
        if instance.maintainer != self.request.user:
            raise PermissionDenied("Only the maintainer can delete this quiz")
        instance.delete()

    def get_serializer_class(self):
        action_serializers = {
            "list": QuizMetaDataSerializer,
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
        permission_classes=[permissions.IsAuthenticated, IsQuizMaintainer],
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
        permission_classes=[permissions.IsAuthenticated],
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
                session = QuizSession.objects.create(quiz=quiz, user=request.user)
            return Response(QuizSessionSerializer(session).data)

        raise MethodNotAllowed(request.method)

    @action(detail=True, methods=["post"], url_path="answer", permission_classes=[permissions.IsAuthenticated])
    def record_answer(self, request, pk=None):
        """Record an answer for the current session."""
        quiz = self.get_object()
        session, _ = QuizSession.get_or_create_active(quiz, request.user)

        question_id = request.data.get("question_id")
        if not question_id:
            return Response({"error": "question_id is required"}, status=400)
        selected_answers = request.data.get("selected_answers", [])

        try:
            question = Question.objects.prefetch_related("answers").get(id=question_id, quiz=quiz)
        except (Question.DoesNotExist, ValueError, TypeError, ValidationError):
            return Response({"error": "Question not found in this quiz"}, status=404)

        selected_ids = set(str(a) for a in selected_answers)

        answers = list(question.answers.all())
        valid_answer_ids = set(str(a.id) for a in answers)
        if not selected_ids.issubset(valid_answer_ids):
            return Response({"error": "One or more selected answers do not belong to this question"}, status=400)

        correct_answer_ids = set(str(a.id) for a in answers if a.is_correct)
        was_correct = correct_answer_ids == selected_ids

        record = AnswerRecord.objects.create(
            session=session,
            question=question,
            selected_answers=list(selected_ids),
            was_correct=was_correct,
        )

        update_fields = []
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
                except (ValueError, TypeError, ValidationError):
                    return Response({"error": "next_question must be a valid question in this quiz"}, status=400)
                if not exists:
                    return Response({"error": "next_question must be a valid question in this quiz"}, status=400)
            session.current_question_id = next_question_id
            update_fields.append("current_question_id")

        if update_fields:
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
            404: OpenApiResponse(description="Not Found"),
            429: OpenApiResponse(description="Too Many Requests"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[permissions.IsAuthenticated],
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
            maintainer=request.user,
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
                    image=q.image,
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
                        image=answer.image,
                        is_correct=answer.is_correct,
                    )
                )

        Answer.objects.bulk_create(new_answers)

        new_quiz = Quiz.objects.prefetch_related("questions__answers").get(pk=new_quiz.pk)

        return Response(
            QuizSerializer(new_quiz, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class QuizMetadataView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get quiz metadata",
        responses={
            200: QuizMetaDataSerializer,
        },
    )
    def get(self, request, quiz_id):
        quiz = Quiz.objects.get(id=quiz_id)
        return Response(QuizMetaDataSerializer(quiz, context={"request": request}).data)


class SharedQuizViewSet(viewsets.ModelViewSet):
    queryset = SharedQuiz.objects.all()
    serializer_class = SharedQuizSerializer
    permission_classes = [permissions.IsAuthenticated, IsSharedQuizMaintainerOrReadOnly]

    def get_queryset(self):
        _filter = (
            Q(user=self.request.user, quiz__visibility__gte=1)
            | Q(
                study_group__in=self.request.user.study_groups.all(),
                quiz__visibility__gte=1,
            )
            | Q(quiz__maintainer=self.request.user)
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

        if request.user == quiz.maintainer:
            return Response(
                {"error": "You cannot report issues with your own questions"},
                status=400,
            )

        # Email details
        subject = "Zgłoszenie błędu w pytaniu"
        query_params = urllib.parse.urlencode({"scroll_to": f"question-{data.get('question_id')}"})
        cta_url = f"{settings.FRONTEND_URL}/edit-quiz/{quiz.id}/?{query_params}"

        content = (
            f"{escape(request.user.full_name)} zgłosił błąd w pytaniu "
            f"{escape(str(data.get('question_id')))} quizu {escape(quiz.title)}.\n\n"
            f"{escape(data.get('issue'))}"
        )

        recipient_list = [quiz.maintainer.email]
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
            return Response({"error": str(e)}, status=500)

        return Response({"status": "ok"}, status=201)


class FolderViewSet(viewsets.ModelViewSet):
    serializer_class = FolderSerializer
    queryset = Folder.objects.all()
    permission_classes = [permissions.IsAuthenticated, IsFolderOwner]

    def get_queryset(self):
        return Folder.objects.filter(owner=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["post"], serializer_class=MoveFolderSerializer)
    def move(self, request, pk=None):
        folder = self.get_object()

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            folder.parent_id = serializer.validated_data["parent_id"]
            folder.save()
            return Response({"status": "Folder moved successfully"})

        return Response(serializer.errors)
