import os

import dotenv
from django.contrib.auth import aget_user
from django.http import JsonResponse
from django.shortcuts import render
from usos_api import USOSClient

dotenv.load_dotenv()

USOS_BASE_URL = "https://apps.usos.pwr.edu.pl/"
CONSUMER_KEY = os.getenv("USOS_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("USOS_CONSUMER_SECRET")


def index(request):
    return render(request, "grades/index.html")


async def get_grades(request):
    request_user = await aget_user(request)
    async with USOSClient(USOS_BASE_URL, CONSUMER_KEY, CONSUMER_SECRET) as client:
        client.load_access_token(
            request_user.access_token, request_user.access_token_secret
        )
        grades = await client.helper.get_user_end_grades_with_weights()

    return JsonResponse([grade.dict() for grade in grades], safe=False)


async def get_courses(request):
    term_id = request.GET.get("term_id")
    request_user = await aget_user(request)

    async with USOSClient(USOS_BASE_URL, CONSUMER_KEY, CONSUMER_SECRET) as client:
        client.load_access_token(
            request_user.access_token, request_user.access_token_secret
        )
        ects = await client.course_service.get_user_courses_ects()

        courses = (
            ects.get(term_id, {}).keys()
            if term_id
            else [
                course
                for term_courses in ects.values()
                for course in term_courses.keys()
            ]
        )

        course_objects = await client.course_service.get_courses(
            courses, fields=["id", "name", "terms"]
        )
        term_objects = await client.term_service.get_terms(ects.keys())

        terms_dict = {term.id: term for term in term_objects}

    for course in course_objects:
        course.terms = [
            terms_dict.get(_term.id)
            for _term in course.terms
            if terms_dict.get(_term.id)
        ]

    courses_ects = {
        course: ects_points
        for term_courses in ects.values()
        for course, ects_points in term_courses.items()
    }

    for course in course_objects:
        course.ects_credits_simplified = courses_ects.get(course.id, 0)

    return JsonResponse([course.dict() for course in course_objects], safe=False)
