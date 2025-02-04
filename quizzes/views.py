import asyncio
import ipaddress
import json
import random
import socket
import urllib.parse
from datetime import timedelta
from urllib.parse import urlparse

import aiohttp
from adrf.decorators import api_view as async_api_view
from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import Q
from django.utils import timezone
from mailersend import emails
from rest_framework import permissions, viewsets
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from quizzes.models import Quiz, QuizProgress, SharedQuiz
from quizzes.permissions import IsSharedQuizMaintainerOrReadOnly
from quizzes.serializers import (
    QuizMetaDataSerializer,
    QuizSerializer,
    SharedQuizSerializer,
)


@api_view(["GET"])
def random_question_for_user(request):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)

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


@api_view(["GET"])
def last_used_quizzes(request):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)

    max_quizzes_count = min(request.query_params.get("count", 4), 20)

    last_used_quizzes = [
        qp.quiz
        for qp in QuizProgress.objects.filter(user=request.user).order_by(
            "-last_activity"
        )[:max_quizzes_count]
    ]

    return Response([quiz.to_dict() for quiz in last_used_quizzes])


@api_view(["GET"])
def search_quizzes(request):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)

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
            "user_quizzes": [quiz.to_search_result() for quiz in user_quizzes],
            "shared_quizzes": [
                shared_quiz.quiz.to_search_result() for shared_quiz in shared_quizzes
            ],
            "group_quizzes": [
                shared_quiz.quiz.to_search_result() for shared_quiz in group_quizzes
            ],
            "public_quizzes": [quiz.to_search_result() for quiz in public_quizzes],
        }
    )


# This viewset will only return user's quizzes when listing, but will allow to view all quizzes when retrieving a single quiz.
# This is by design, if the user wants to view shared quizzes, they should use the SharedQuizViewSet and for public quizzes they should use the api_search_quizzes view.
# It will also allow to create, update and delete quizzes only if the user is the maintainer of the quiz.
class QuizViewSet(viewsets.ModelViewSet):
    queryset = Quiz.objects.all()
    serializer_class = QuizSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            if self.action == "list":
                return Quiz.objects.none()
            return Quiz.objects.filter(visibility__gte=2, allow_anonymous=True)
        _filter = Q(maintainer=self.request.user)
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
        serializer.save(
            maintainer=self.request.user, version=serializer.instance.version + 1
        )

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


@api_view(["GET"])
def quiz_metadata(request, quiz_id):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)
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


@async_api_view(["POST"])
async def import_quiz_from_link(request):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)

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


@api_view(["POST"])
def report_question_issue(request):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)
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

    mailer = emails.NewEmail()
    mail_body = {}

    mail_from = {
        "name": "Testownik",
        "email": "report@testownik.live",
    }

    recipients = [
        {
            "name": quiz.maintainer.full_name,
            "email": quiz.maintainer.email,
        }
    ]

    reply_to = {
        "name": request.user.full_name,
        "email": request.user.email,
    }

    mailer.set_mail_from(mail_from, mail_body)
    mailer.set_mail_to(recipients, mail_body)
    mailer.set_subject("Zgłoszenie błędu w pytaniu", mail_body)
    mailer.set_plaintext_content(
        f"{request.user.full_name} zgłosił błąd w pytaniu {data.get('question_id')} quizu {quiz.title}.\n\n{data.get('issue')}\n\nKliknij w link, aby przejść do edycji bazy: https://testownik.live/edit-quiz/{quiz.id}/?scroll_to=question-{data.get('question_id')}",
        mail_body,
    )
    mailer.set_reply_to(reply_to, mail_body)

    try:
        mailer.send(mail_body)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

    return Response({"status": "ok"}, status=201)


@api_view(["GET", "POST", "DELETE"])
def quiz_progress(request, quiz_id):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)
    if request.method == "GET":
        try:
            quiz_progress, _ = QuizProgress.objects.get_or_create(
                quiz_id=quiz_id, user=request.user
            )
        except QuizProgress.MultipleObjectsReturned:
            # This should never happen, but apparently it does sometimes
            # Remove duplicates except the one with the highest last_activity
            duplicates = QuizProgress.objects.filter(
                quiz_id=quiz_id, user=request.user
            ).order_by("-last_activity")[1:]
            for duplicate in duplicates:
                duplicate.delete()
            quiz_progress = QuizProgress.objects.get(quiz_id=quiz_id, user=request.user)
        return Response(quiz_progress.to_dict())
    elif request.method == "POST":
        data = json.loads(request.body)
        try:
            quiz_progress, _ = QuizProgress.objects.get_or_create(
                quiz_id=quiz_id, user=request.user
            )
        except QuizProgress.MultipleObjectsReturned:
            # This should never happen, but apparently it does sometimes
            # Remove duplicates except the one with the highest last_activity
            duplicates = QuizProgress.objects.filter(
                quiz_id=quiz_id, user=request.user
            ).order_by("-last_activity")[1:]
            for duplicate in duplicates:
                duplicate.delete()
            quiz_progress = QuizProgress.objects.get(quiz_id=quiz_id, user=request.user)

        for field in [
            "current_question",
            "reoccurrences",
            "correct_answers_count",
            "wrong_answers_count",
        ]:
            if field in data:
                setattr(quiz_progress, field, data[field])

        if "study_time" in data:
            quiz_progress.study_time = timedelta(seconds=data["study_time"])

        quiz_progress.save()
        return Response({"status": "updated"})
    elif request.method == "DELETE":
        quiz_progress = QuizProgress.objects.get(quiz_id=quiz_id, user=request.user)
        quiz_progress.delete()
        return Response({"status": "deleted"})
    else:
        return Response({"error": "Method not allowed"}, status=405)
