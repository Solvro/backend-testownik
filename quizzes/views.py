import json
from datetime import timedelta

import requests
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from quizzes.models import Quiz, QuizProgress, SharedQuiz


def index(request):
    return render(request, "quizzes/index.html")


def quiz(request, quiz_id):
    quiz_obj = Quiz.objects.get(id=quiz_id)
    if not quiz_obj:
        return HttpResponse("Quiz not found", status=404)
    if not quiz_obj.allow_anonymous and not request.user.is_authenticated:
        return render(request, "base.html", status=401)
    if request.user.is_authenticated:
        user_settings = {
            "syncProgress": request.user.settings.sync_progress,
            "initialRepetitions": request.user.settings.initial_repetitions,
            "wrongAnswerRepetitions": request.user.settings.wrong_answer_repetitions,
        }
    else:
        user_settings = {
            "syncProgress": False,
            "initialRepetitions": 1,
            "wrongAnswerRepetitions": 1,
        }
    return render(
        request,
        "quizzes/quiz.html",
        {
            "quiz_id": quiz_id,
            "user_settings": json.dumps(user_settings),
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
