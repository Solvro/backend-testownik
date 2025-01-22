import os

import dotenv
from adrf.decorators import api_view as async_api_view
from rest_framework.response import Response
from usos_api import USOSClient

from users.models import Term

dotenv.load_dotenv()

USOS_BASE_URL = "https://apps.usos.pwr.edu.pl/"
CONSUMER_KEY = os.getenv("USOS_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("USOS_CONSUMER_SECRET")


@async_api_view(["GET"])
async def get_grades(request):
    term_id = request.GET.get("term_id")
    request_user = request.user

    async with USOSClient(
        USOS_BASE_URL, CONSUMER_KEY, CONSUMER_SECRET, trust_env=True
    ) as client:
        client.load_access_token(
            request_user.access_token, request_user.access_token_secret
        )
        ects = await client.course_service.get_user_courses_ects()

        # Check if terms are already in the database
        term_ids = ects.keys()
        existing_terms = Term.objects.filter(id__in=ects.keys())
        existing_term_ids = [
            term_id async for term_id in existing_terms.values_list("id", flat=True)
        ]

        # Find missing terms
        missing_term_ids = set(term_ids) - set(existing_term_ids)

        # Get terms from the database
        terms = []
        async for term in existing_terms:
            terms.append(term)

        # Fetch missing terms from the API
        if missing_term_ids:
            fetched_terms = await client.term_service.get_terms(missing_term_ids)
            # Save fetched terms to the database
            for term in fetched_terms:
                term_obj, _ = await Term.objects.aupdate_or_create(
                    id=term.id,
                    defaults={
                        "name": term.name.pl,
                        "start_date": term.start_date,
                        "end_date": term.end_date,
                        "finish_date": term.finish_date,
                    },
                )
                terms.append(term_obj)

        course_editions = await client.course_service.get_user_course_editions()
        grades = await client.grade_service.get_grades_by_terms(
            term_id or [term.id for term in terms]
        )

    courses_ects = {
        course: ects_points
        for term_courses in ects.values()
        for course, ects_points in term_courses.items()
    }

    return Response(
        {
            "terms": sorted(
                [
                    {
                        "id": term.id,
                        "name": term.name,
                        "start_date": term.start_date,
                        "end_date": term.end_date,
                        "is_current": term.is_current,
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
