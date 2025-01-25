import json
import random
import urllib.parse
from datetime import timedelta

import requests
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
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
from users.models import UserSettings


def quiz(request, quiz_id):
    quiz_obj = Quiz.objects.get(id=quiz_id)
    if not quiz_obj:
        return HttpResponse("Quiz not found", status=404)
    if not quiz_obj.allow_anonymous and not request.user.is_authenticated:
        return render(request, "base.html", status=401)
    if request.user.is_authenticated:
        user_settings, created = UserSettings.objects.get_or_create(user=request.user)
        user_settings_data = {
            "syncProgress": user_settings.sync_progress,
            "initialRepetitions": user_settings.initial_reoccurrences,
            "wrongAnswerRepetitions": user_settings.wrong_answer_reoccurrences,
        }
    else:
        user_settings_data = {
            "syncProgress": False,
            "initialRepetitions": 1,
            "wrongAnswerRepetitions": 1,
        }
    QuizProgress.objects.get_or_create(quiz_id=quiz_id, user=request.user)[
        0
    ].save()  # update last_activity
    return render(
        request,
        "quizzes/quiz.html",
        {
            "quiz_id": quiz_id,
            "user_settings": json.dumps(user_settings_data),
            "allow_anonymous": quiz_obj.allow_anonymous,
        },
    )


def quiz_legacy_api(request, quiz_id):
    quiz = Quiz.objects.get(id=quiz_id)
    return JsonResponse(quiz.to_dict())


def quiz_progress_legacy_api(request, quiz_id):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Unauthorized"}, status=401)
    if request.method == "GET":
        quiz_progress, _ = QuizProgress.objects.get_or_create(
            quiz_id=quiz_id, user=request.user
        )
        return JsonResponse(quiz_progress.to_dict())
    elif request.method == "POST":
        data = json.loads(request.body)
        quiz_progress, _ = QuizProgress.objects.get_or_create(
            quiz_id=quiz_id, user=request.user
        )

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
        return JsonResponse({"status": "updated"})
    elif request.method == "DELETE":
        quiz_progress = QuizProgress.objects.get(quiz_id=quiz_id, user=request.user)
        quiz_progress.delete()
        return JsonResponse({"status": "deleted"})
    else:
        return JsonResponse({"error": "Method not allowed"}, status=405)


def random_question_for_user(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    quizzes_progress = QuizProgress.objects.filter(
        user=request.user, last_activity__gt=timezone.now() - timedelta(days=90)
    ).order_by("?")

    for quiz_progress in quizzes_progress:
        if quiz_progress.quiz.questions:
            random_question = random.choice(quiz_progress.quiz.questions)
            random_question["quiz_id"] = quiz_progress.quiz.id
            random_question["quiz_title"] = quiz_progress.quiz.title
            return JsonResponse(random_question)

    return JsonResponse({"error": "No quizzes found"}, status=404)


@api_view(["GET"])
def api_random_question_for_user(request):
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
def api_last_used_quizzes(request):
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
def api_search_quizzes(request):
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
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            if self.action == "list":
                return Quiz.objects.none()
            return Quiz.objects.filter(visibility__gte=3, allow_anonymous=True)
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
def quiz_metadata_api(request, quiz_id):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)
    quiz = Quiz.objects.get(id=quiz_id)
    return Response(QuizMetaDataSerializer(quiz, context={"user": request.user}).data)


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
            | Q(quiz__visibility__gte=3)
        )
        if self.request.query_params.get("quiz"):
            _filter |= Q(quiz__maintainer=self.request.user)
            _filter &= Q(quiz_id=self.request.query_params.get("quiz"))
        return SharedQuiz.objects.filter(_filter)

    def perform_create(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        instance.delete()


@api_view(["POST"])
def import_quiz_from_link_api(request):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)
    data = json.loads(request.body)
    try:
        r = requests.get(data.get("link"))
        r.raise_for_status()
        _quiz = r.json()
    except requests.exceptions.RequestException as e:
        return Response({"error": str(e)}, status=400)

    quiz_obj = Quiz.objects.create(
        title=_quiz.get("title", ""),
        description=_quiz.get("description", ""),
        maintainer=request.user,
        questions=_quiz.get("questions", []),
    )
    return Response(quiz_obj.to_dict(), status=201)


@api_view(["POST"])
def report_question_issue_api(request):
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
        f"{request.user.full_name} zgłosił błąd w pytaniu {data.get('question_id')} bazy {quiz.title}.\n\n{data.get('issue')}\n\nKliknij w link, aby przejść do edycji bazy: https://testownik.live/edit-quiz/{quiz.id}/#question-{data.get('question_id')}",
        mail_body,
    )
    mailer.set_reply_to(reply_to, mail_body)

    try:
        mailer.send(mail_body)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

    return Response({"status": "ok"}, status=201)


@api_view(["GET", "POST", "DELETE"])
def quiz_progress_api(request, quiz_id):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)
    if request.method == "GET":
        quiz_progress, _ = QuizProgress.objects.get_or_create(
            quiz_id=quiz_id, user=request.user
        )
        return Response(quiz_progress.to_dict())
    elif request.method == "POST":
        data = json.loads(request.body)
        quiz_progress, _ = QuizProgress.objects.get_or_create(
            quiz_id=quiz_id, user=request.user
        )

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
