import json

import requests
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from quizzes.models import Quiz, SharedQuiz


def index(request):
    return render(request, "quizzes/index.html")


def quiz(request, quiz_id):
    quiz_obj = Quiz.objects.get(id=quiz_id)
    return render(request, "quizzes/quiz.html", {"quiz_id": quiz_id, "allow_anonymous": quiz_obj.allow_anonymous})


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
