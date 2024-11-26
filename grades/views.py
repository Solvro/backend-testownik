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
    term_id = request.GET.get("term_id")
    request_user = await aget_user(request)

    async with USOSClient(USOS_BASE_URL, CONSUMER_KEY, CONSUMER_SECRET) as client:
        client.load_access_token(
            request_user.access_token, request_user.access_token_secret
        )
        ects = await client.course_service.get_user_courses_ects()
        terms = await client.term_service.get_terms(ects.keys())

        course_editions = await client.course_service.get_user_course_editions()
        grades = await client.grade_service.get_grades_by_terms(
            term_id or [term.id for term in terms]
        )

    courses_ects = {
        course: ects_points
        for term_courses in ects.values()
        for course, ects_points in term_courses.items()
    }

    return JsonResponse(
        {
            "terms": sorted(
                [
                    {
                        "id": term.id,
                        "name": term.name.pl,
                        "start_date": term.start_date,
                        "end_date": term.end_date,
                        "is_current": term.is_ongoing,
                    }
                    for term in terms
                ],
                key=lambda term: term["start_date"],
                reverse=True,
            ),
            "courses": [
                {
                    "course_id": course_edition.course_id,
                    "course_name": course_edition.course_name.pl,
                    "term_id": course_edition.term_id,
                    "ects": courses_ects.get(course_edition.course_id, 0),
                    "grades": [
                        {
                            "value": grade.value,
                            "value_symbol": grade.value_symbol,
                            "value_description": grade.value_description.pl,
                            "counts_into_average": grade.counts_into_average,
                        }
                        for grade in grades[course_edition.term_id][
                            course_edition.course_id
                        ]["course_grades"]
                    ],
                    "passing_status": course_edition.passing_status,
                }
                for course_edition in course_editions
            ],
        }
    )
