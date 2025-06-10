import asyncio
import ipaddress
import json
import random
import socket
import urllib.parse
from datetime import timedelta
from urllib.parse import urlparse

import aiohttp
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import URLValidator
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample, OpenApiParameter
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.views import APIView

from quizzes.models import Quiz, QuizProgress, SharedQuiz, QuizCollaborator
from quizzes.permissions import IsSharedQuizMaintainerOrReadOnly, IsQuizMaintainerOrCollaborator
from quizzes.serializers import (
    QuizMetaDataSerializer,
    QuizSerializer,
    SharedQuizSerializer,
    QuizCollaboratorSerializer,
)


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
                description="Randomly selected question from user's recent quizzes"
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
                    "quiz_title": "Geography Quiz"
                },
                status_codes=["200"]
            )
        ]
    )
    def get(self, request):
        quizzes_progress = QuizProgress.objects.filter(
            user=request.user,
            last_activity__gt=timezone.now() - timedelta(days=90)
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
            401: OpenApiResponse(description="Unauthorized")
        },
        parameters=[
            OpenApiParameter(
                name="limit",
                required=False,
                type=int,
                location=OpenApiParameter.QUERY,
                description="Maximum number of recent quizzes to return (max: 20)",
            )
        ]
    )
    def get(self, request):
        max_quizzes_count = min(int(request.query_params.get("limit", 4)), 20)

        last_used_quizzes = [
            qp.quiz
            for qp in QuizProgress.objects.filter(user=request.user).order_by("-last_activity")[:max_quizzes_count]
        ]

        return Response([quiz.to_dict() for quiz in last_used_quizzes])


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
            400: OpenApiResponse(description="Missing query parameter")
        },
        parameters=[
            OpenApiParameter(
                name="query",
                required=True,
                type=str,
                location=OpenApiParameter.QUERY,
                description="Search term for quiz titles"
            )
        ]
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

        return Response({
            "user_quizzes": [q.to_search_result() for q in user_quizzes],
            "shared_quizzes": [q.quiz.to_search_result() for q in shared_quizzes],
            "group_quizzes": [q.quiz.to_search_result() for q in group_quizzes],
            "public_quizzes": [q.to_search_result() for q in public_quizzes],
        })


# This viewset will only return user's quizzes when listing, but will allow to view all quizzes when retrieving a single quiz.
# This is by design, if the user wants to view shared quizzes, they should use the SharedQuizViewSet and for public quizzes they should use the api_search_quizzes view.
# It will also allow to create, update and delete quizzes only if the user is the maintainer of the quiz.
class QuizViewSet(viewsets.ModelViewSet):
    queryset = Quiz.objects.all()
    serializer_class = QuizSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsQuizMaintainerOrCollaborator]

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            if self.action == "list":
                return Quiz.objects.none()
            return Quiz.objects.filter(visibility__gte=2, allow_anonymous=True)
        _filter = Q(maintainer=self.request.user) | Q(collaborators__user=self.request.user, collaborators__status=1)
        if self.action == "retrieve":
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
        quiz = serializer.instance
        if not quiz.can_edit(self.request.user):
            raise PermissionDenied("You don't have permission to edit this quiz")
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
        if request.user != self.get_object().maintainer:
            return Response(
                {"error": "You are not the maintainer of this quiz"}, status=403
            )
        return super().update(request, *args, **kwargs)


class QuizMetadataView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get quiz metadata",
        responses={
            200: QuizMetaDataSerializer,
        }
    )
    def get(self, request, quiz_id):
        quiz = Quiz.objects.get(id=quiz_id)
        return Response(QuizMetaDataSerializer(quiz, context={"user": request.user}).data)


class SharedQuizViewSet(viewsets.ModelViewSet):
    queryset = SharedQuiz.objects.all()
    serializer_class = SharedQuizSerializer
    permission_classes = [permissions.IsAuthenticated, IsSharedQuizMaintainerOrReadOnly]

    def get_queryset(self):
        _filter = Q(user=self.request.user, quiz__visibility__gte=1) | Q(
            study_group__in=self.request.user.study_groups.all(),
            quiz__visibility__gte=1,
        )
        if self.request.query_params.get("quiz"):
            _filter |= Q(quiz__maintainer=self.request.user)
            _filter &= Q(quiz_id=self.request.query_params.get("quiz"))
        return SharedQuiz.objects.filter(_filter)

    def perform_create(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        instance.delete()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"user": self.request.user})
        return context


class ImportQuizFromLinkView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Import quiz from external link",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "link": {"type": "string", "format": "uri"}
                },
                "required": ["link"]
            }
        },
        responses={
            201: QuizSerializer,
            400: OpenApiResponse(description="Validation or fetch failure"),
            401: OpenApiResponse(description="Unauthorized")
        }
    )
    async def post(self, request):

        # Sanitize and validate the link
        data = json.loads(request.body)
        link = data.get("link")
        if not link:
            return Response({"error": "Link parameter is required"}, status=400)

        # Validate URL format
        validator = URLValidator()
        try:
            validator(link)
        except ValidationError:
            return Response({"error": "Invalid URL"}, status=400)

        # Parse and validate the URL's hostname and scheme
        parsed_url = urlparse(link)
        if parsed_url.scheme not in ["https"]:
            return Response({"error": "Only HTTPS protocol is allowed"}, status=400)

        hostname = parsed_url.hostname
        try:
            # Check if hostname is an IP address
            ipaddress.ip_address(hostname)
            return Response(
                {"error": "IP addresses are not allowed, only public domains"}, status=400
            )
        except ValueError:
            # If not an IP, ensure the hostname is valid
            if not hostname or "." not in hostname:
                return Response({"error": "Invalid domain name"}, status=400)

        try:
            # Resolve the hostname to ensure it is valid and not private
            ip = socket.gethostbyname(hostname)
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved:
                return Response(
                    {"error": "Private, loopback, or reserved addresses are not allowed"},
                    status=400,
                )
        except Exception as e:
            return Response({"error": f"Hostname resolution failed: {str(e)}"}, status=400)

        try:
            # Use aiohttp to download the file asynchronously
            async with aiohttp.ClientSession() as session:
                async with session.get(link, timeout=5) as response:
                    # Check for HTTP status and content type
                    if response.status != 200:
                        return Response({"error": "Failed to fetch the file"}, status=400)

                    content_type = response.headers.get("Content-Type", "")
                    if (
                            "application/json" not in content_type
                            and "text/json" not in content_type
                            and "text/plain" not in content_type
                    ):
                        return Response(
                            {"error": "The file is not a valid JSON file"}, status=400
                        )

                    # Check file size
                    content_length = int(response.headers.get("Content-Length", 0))
                    max_file_size = 5 * 1024 * 1024  # 5 MB
                    if content_length > max_file_size:
                        return Response(
                            {"error": "File size exceeds the 5MB limit"}, status=400
                        )

                    # Parse JSON content
                    try:
                        if "text/plain" in content_type:
                            quiz_data = json.loads(await response.text())
                        else:
                            quiz_data = await response.json()
                    except aiohttp.ContentTypeError:
                        return Response({"error": "Invalid JSON format"}, status=400)

                    # Validate quiz data structure
                    required_fields = ["title", "description", "questions"]
                    for field in required_fields:
                        if field not in quiz_data:
                            return Response(
                                {"error": f"Missing required field: {field}"}, status=400
                            )

        except asyncio.TimeoutError:
            return Response({"error": "Request timed out"}, status=400)
        except aiohttp.ClientError as e:
            return Response({"error": f"Request failed: {str(e)}"}, status=400)

        # Create a new quiz object using serializer
        serializer = QuizSerializer(data=quiz_data)
        if serializer.is_valid():
            quiz = await sync_to_async(serializer.save)(maintainer=request.user)
            return Response(QuizSerializer(quiz).data, status=201)
        else:
            return Response(serializer.errors, status=400)


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
                "required": ["quiz_id", "question_id", "issue"]
            }
        },
        responses={
            201: OpenApiResponse(description="Issue reported successfully"),
            400: OpenApiResponse(description="Missing or invalid data"),
            401: OpenApiResponse(description="Unauthorized"),
            404: OpenApiResponse(description="Quiz not found"),
            500: OpenApiResponse(description="Email sending failed")
        }
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
                {"error": "You cannot report issues with your own questions"}, status=400
            )

        # Email details
        subject = "Zgłoszenie błędu w pytaniu"
        message = (
            f"{request.user.full_name} zgłosił błąd w pytaniu {data.get('question_id')} quizu {quiz.title}.\n\n"
            f"{data.get('issue')}\n\n"
            f"Kliknij w link, aby przejść do edycji bazy: https://testownik.solvro.pl/edit-quiz/{quiz.id}/?scroll_to=question-{data.get('question_id')}"
        )

        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = [quiz.maintainer.email]
        reply_to = [request.user.email]

        try:
            email = EmailMessage(
                subject=subject,
                body=message,
                from_email=from_email,
                to=recipient_list,
                reply_to=reply_to,  # This ensures replies go to the user who reported the issue
            )
            email.send(fail_silently=False)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

        return Response({"status": "ok"}, status=201)


class QuizProgressView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get, update or delete quiz progress",
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
                }
            },
            401: OpenApiResponse(description="Unauthorized"),
            403: OpenApiResponse(description="Forbidden"),
            404: OpenApiResponse(description="Not Found")
        }
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

    def post(self, request, quiz_id):
        data = json.loads(request.body)
        try:
            quiz_progress, _ = QuizProgress.objects.get_or_create(quiz_id=quiz_id, user=request.user)
        except QuizProgress.MultipleObjectsReturned:
            duplicates = QuizProgress.objects.filter(quiz_id=quiz_id, user=request.user).order_by("-last_activity")[1:]
            for duplicate in duplicates:
                duplicate.delete()
            quiz_progress = QuizProgress.objects.get(quiz_id=quiz_id, user=request.user)

        for field in ["current_question", "reoccurrences", "correct_answers_count", "wrong_answers_count"]:
            if field in data:
                setattr(quiz_progress, field, data[field])

        if "study_time" in data:
            quiz_progress.study_time = timedelta(seconds=data["study_time"])

        quiz_progress.save()
        return Response({"status": "updated"})

    def delete(self, request, quiz_id):
        quiz_progress = QuizProgress.objects.get(quiz_id=quiz_id, user=request.user)
        quiz_progress.delete()
        return Response({"status": "deleted"})


class QuizCollaboratorViewSet(viewsets.ModelViewSet):
    serializer_class = QuizCollaboratorSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {
        'quiz': ['exact'],
        'status': ['exact'],
        'user': ['exact'],
    }
    queryset = QuizCollaborator.objects.none()  # Default queryset for schema generation

    def get_queryset(self):
        # Skip authentication check for schema generation
        if getattr(self, 'swagger_fake_view', False):
            return QuizCollaborator.objects.none()

        return QuizCollaborator.objects.filter(
            Q(quiz__maintainer=self.request.user) | Q(user=self.request.user)
        ).distinct()

    def perform_create(self, serializer):
        quiz = serializer.validated_data['quiz']
        if quiz.maintainer != self.request.user:
            raise PermissionDenied("Only the quiz maintainer can add collaborators")
        serializer.save(invited_by=self.request.user)

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        collaborator = self.get_object()
        if collaborator.user != request.user:
            raise PermissionDenied("You can only accept your own invitations")
        if collaborator.status != 0:
            return Response({"error": "This invitation has already been processed"}, status=400)
        collaborator.status = 1
        collaborator.save()
        return Response(self.get_serializer(collaborator).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        collaborator = self.get_object()
        if collaborator.user != request.user:
            raise PermissionDenied("You can only reject your own invitations")
        if collaborator.status != 0:
            return Response({"error": "This invitation has already been processed"}, status=400)
        collaborator.status = 2
        collaborator.save()
        return Response(self.get_serializer(collaborator).data)
