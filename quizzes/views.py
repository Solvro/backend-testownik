import json
import random
import urllib.parse
from datetime import timedelta

from django.conf import settings
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
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from quizzes.models import Folder, Quiz, QuizProgress, SharedQuiz
from quizzes.permissions import (
    IsFolderOwner,
    IsQuizMaintainer,
    IsQuizMaintainerOrCollaborator,
    IsSharedQuizMaintainerOrReadOnly,
)
from quizzes.serializers import (
    FolderSerializer,
    MoveFolderSerializer,
    MoveQuizSerializer,
    QuizMetaDataSerializer,
    QuizSerializer,
    SharedQuizSerializer,
)
from quizzes.services.notifications import (
    notify_quiz_shared_to_groups,
    notify_quiz_shared_to_users,
)
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
        quizzes_progress = QuizProgress.objects.filter(
            user=request.user, last_activity__gt=timezone.now() - timedelta(days=90)
        ).order_by("?")

        for quiz_progress in quizzes_progress:
            if quiz_progress.quiz.questions:
                random_question = random.choice(quiz_progress.quiz.questions)
                random_question["quiz_id"] = quiz_progress.quiz.id
                random_question["quiz_title"] = quiz_progress.quiz.title
                return Response(random_question)

        return Response({"error": "No quizzes found"}, status=404)


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
        max_quizzes_count = min(int(request.query_params.get("limit", 4)), 20)

        last_used_quizzes = [
            qp.quiz
            for qp in QuizProgress.objects.filter(user=request.user).order_by("-last_activity")[:max_quizzes_count]
        ]

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

        user_quizzes = Quiz.objects.filter(maintainer=request.user, title__icontains=query)
        shared_quizzes = SharedQuiz.objects.filter(
            user=request.user, quiz__title__icontains=query, quiz__visibility__gte=1
        )
        group_quizzes = SharedQuiz.objects.filter(
            study_group__in=request.user.study_groups.all(),
            quiz__title__icontains=query,
            quiz__visibility__gte=1,
        )
        public_quizzes = Quiz.objects.filter(title__icontains=query, visibility__gte=3)

        return Response(
            {
                "user_quizzes": [q.to_search_result() for q in user_quizzes],
                "shared_quizzes": [q.quiz.to_search_result() for q in shared_quizzes],
                "group_quizzes": [q.quiz.to_search_result() for q in group_quizzes],
                "public_quizzes": [q.to_search_result() for q in public_quizzes],
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
        if not self.request.user.is_authenticated:
            if self.action == "list":
                return Quiz.objects.none()
            return Quiz.objects.filter(visibility__gte=2, allow_anonymous=True)
        _filter = Q(maintainer=self.request.user)
        if self.action == "retrieve" or self.action == "update":
            _filter |= Q(visibility__gte=3)
            _filter |= Q(visibility__gte=2)
            _filter |= Q(visibility__gte=1, sharedquiz__user=self.request.user)
            _filter |= Q(
                visibility__gte=1,
                sharedquiz__study_group__in=self.request.user.study_groups.all(),
            )
        return Quiz.objects.filter(_filter).distinct()

    def perform_create(self, serializer):
        serializer.save(maintainer=self.request.user)

    def perform_update(self, serializer):
        serializer.save(version=serializer.instance.version + 1)

    def perform_destroy(self, instance):
        if instance.maintainer == self.request.user:
            instance.delete()
        else:
            raise PermissionDenied

    def get_serializer_class(self):
        if self.action == "list":
            return QuizMetaDataSerializer
        return QuizSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action == "list":
            context.update({"user": self.request.user})
        return context

    def update(self, request, *args, **kwargs):
        quiz = self.get_object()
        if not quiz.can_edit(request.user):
            return Response({"error": "You do not have permission to edit this quiz"}, status=403)
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


class QuizProgressView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get quiz progress",
        responses={
            200: {
                "type": "object",
                "properties": {
                    "current_question": {"type": "integer"},
                    "correct_answers_count": {"type": "integer"},
                    "wrong_answers_count": {"type": "integer"},
                    "study_time": {"type": "number"},
                    "last_activity": {"type": "string", "format": "date-time"},
                    "reoccurrences": {"type": "array", "items": {"type": "integer"}},
                    "tips": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "example": {"0": "Check math formulas", "5": "Think about second laboratories"},
                    },
                },
            },
            401: OpenApiResponse(description="Unauthorized"),
            403: OpenApiResponse(description="Forbidden"),
            404: OpenApiResponse(description="Not Found"),
        },
    )
    def get(self, request, quiz_id):
        try:
            quiz_progress, _ = QuizProgress.objects.get_or_create(quiz_id=quiz_id, user=request.user)
        except QuizProgress.MultipleObjectsReturned:
            duplicates = QuizProgress.objects.filter(quiz_id=quiz_id, user=request.user).order_by("-last_activity")[1:]
            for duplicate in duplicates:
                duplicate.delete()
            quiz_progress = QuizProgress.objects.get(quiz_id=quiz_id, user=request.user)
        return Response(quiz_progress.to_dict())

    @extend_schema(
        summary="Update quiz progress",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "current_question": {"type": "integer"},
                    "correct_answers_count": {"type": "integer"},
                    "wrong_answers_count": {"type": "integer"},
                    "study_time": {"type": "number"},
                    "reoccurrences": {"type": "array", "items": {"type": "integer"}},
                    "tips": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "example": {"0": "Check math formulas", "5": "Think about second laboratories"},
                    },
                },
            }
        },
        responses={
            200: OpenApiResponse(description="Quiz progress updated"),
            401: OpenApiResponse(description="Unauthorized"),
            400: OpenApiResponse(description="Invalid data"),
        },
    )
    def post(self, request, quiz_id):
        data = json.loads(request.body)
        try:
            quiz_progress, _ = QuizProgress.objects.get_or_create(quiz_id=quiz_id, user=request.user)
        except QuizProgress.MultipleObjectsReturned:
            duplicates = QuizProgress.objects.filter(quiz_id=quiz_id, user=request.user).order_by("-last_activity")[1:]
            for duplicate in duplicates:
                duplicate.delete()
            quiz_progress = QuizProgress.objects.get(quiz_id=quiz_id, user=request.user)

        for field in ["current_question", "reoccurrences", "correct_answers_count", "wrong_answers_count", "tips"]:
            if field in data:
                setattr(quiz_progress, field, data[field])

        if "study_time" in data:
            quiz_progress.study_time = timedelta(seconds=data["study_time"])

        quiz_progress.save()
        return Response({"status": "updated"})

    @extend_schema(
        summary="Delete quiz progress",
        responses={
            200: OpenApiResponse(description="Progress deleted"),
            401: OpenApiResponse(description="Unauthorized"),
            404: OpenApiResponse(description="Not Found"),
        },
    )
    def delete(self, request, quiz_id):
        quiz_progress = QuizProgress.objects.get(quiz_id=quiz_id, user=request.user)
        quiz_progress.delete()
        return Response({"status": "deleted"})


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
