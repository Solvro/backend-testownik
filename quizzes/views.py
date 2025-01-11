import json
import random
import urllib.parse
from datetime import timedelta

import requests
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from quizzes.models import Quiz, QuizProgress, SharedQuiz
from users.models import UserSettings


def index(request):
    return render(request, "quizzes/index.html")


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
            "initialRepetitions": user_settings.initial_repetitions,
            "wrongAnswerRepetitions": user_settings.wrong_answer_repetitions,
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


def import_quiz(request):
    if request.method == "POST":
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Unauthorized"}, status=401)
        data = json.loads(request.body)
        if data.get("type") == "link":
            try:
                r = requests.get(data.get("data"))
                r.raise_for_status()
                _quiz = r.json()
            except requests.exceptions.RequestException as e:
                return JsonResponse({"error": str(e)}, status=400)
        elif data.get("type") == "json":
            _quiz = data.get("data")
        else:
            return JsonResponse({"error": "Invalid type"}, status=400)

        quiz_obj = Quiz.objects.create(
            title=_quiz.get("title", ""),
            description=_quiz.get("description", ""),
            maintainer=request.user,
            questions=_quiz.get("questions", []),
        )
        return JsonResponse({"id": quiz_obj.id})

    return render(request, "quizzes/import_quiz.html")


def import_quiz_old(request):
    return render(request, "quizzes/import_quiz_old.html")


def quiz_api(request, quiz_id):
    quiz = Quiz.objects.get(id=quiz_id)
    return JsonResponse(quiz.to_dict())


def quiz_progress_api(request, quiz_id):
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

    last_used_quizzes = [
        qp.quiz
        for qp in QuizProgress.objects.filter(user=request.user).order_by(
            "-last_activity"
        )[:4]
    ]

    return Response([quiz.to_dict() for quiz in last_used_quizzes])


def quizzes(request):
    if not request.user.is_authenticated:
        return render(request, "quizzes/quizzes.html")
    user_quizzes = Quiz.objects.filter(maintainer=request.user)
    shared_quizzes = SharedQuiz.objects.filter(user=request.user)
    group_quizzes = SharedQuiz.objects.filter(
        study_group__in=request.user.study_groups.all()
    )
    return render(
        request,
        "quizzes/quizzes.html",
        {
            "user_quizzes": user_quizzes,
            "shared_quizzes": shared_quizzes,
            "group_quizzes": group_quizzes,
        },
    )


def edit_quiz(request, quiz_id):
    return HttpResponse("Not implemented", status=501)


@api_view(["GET"])
def api_search_quizzes(request):
    if not request.user.is_authenticated:
        return Response({"error": "Unauthorized"}, status=401)

    query = urllib.parse.unquote(request.query_params.get("query", ""))

    if not query:
        return Response({"error": "Query parameter is required"}, status=400)

    user_quizzes = Quiz.objects.filter(maintainer=request.user, title__icontains=query)
    shared_quizzes = SharedQuiz.objects.filter(user=request.user, quiz__title__icontains=query, quiz__visibility__gte=1)
    group_quizzes = SharedQuiz.objects.filter(
        study_group__in=request.user.study_groups.all(), quiz__title__icontains=query, quiz__visibility__gte=1
    )
    public_quizzes = Quiz.objects.filter(title__icontains=query, visibility__gte=3)
    return Response(
        {
            "user_quizzes": [quiz.to_search_result() for quiz in user_quizzes],
            "shared_quizzes": [shared_quiz.quiz.to_search_result() for shared_quiz in shared_quizzes],
            "group_quizzes": [shared_quiz.quiz.to_search_result() for shared_quiz in group_quizzes],
            "public_quizzes": [quiz.to_search_result() for quiz in public_quizzes],
        }
    )