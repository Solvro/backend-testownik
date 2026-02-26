import logging
import os

import dotenv
from adrf.decorators import api_view as async_api_view
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from usos_api import USOSClient

from users.models import Term

dotenv.load_dotenv()

logger = logging.getLogger(__name__)

USOS_BASE_URL = "https://apps.usos.pwr.edu.pl/"
CONSUMER_KEY = os.getenv("USOS_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("USOS_CONSUMER_SECRET")


async def get_user_courses_ects_safe(client) -> dict[str, dict[str, float]]:
    """
    Safe wrapper that handles None or invalid ECTS values by setting them to 0.0.
    """
    response = await client.connection.get("services/courses/user_ects_points", params={})

    if not isinstance(response, dict):
        logger.error(
            "USOS API user_ects_points response has invalid type: %s",
            type(response).__name__,
        )
        raise APIException("Invalid response from USOS API (user_ects_points). Expected dict.")

    logger.debug("USOS API user_ects_points response: %s terms found", len(response))

    result = {}
    missing_or_invalid_ects_count = 0
    total_courses = 0

    for term_id, courses in response.items():
        if courses and isinstance(courses, dict):
            filtered_courses = {}
            for course_id, ects_value in courses.items():
                total_courses += 1

                if ects_value is not None:
                    try:
                        filtered_courses[course_id] = float(ects_value)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Cannot convert ECTS '{ects_value}' for {course_id}: {e}")
                        filtered_courses[course_id] = 0.0
                        missing_or_invalid_ects_count += 1
                else:
                    filtered_courses[course_id] = 0.0
                    missing_or_invalid_ects_count += 1
                    logger.debug(f"Course {course_id} in {term_id} has no ECTS, setting to 0")

            if filtered_courses:
                result[term_id] = filtered_courses

    if missing_or_invalid_ects_count > 0:
        logger.info(f"Found {missing_or_invalid_ects_count}/{total_courses} courses with None ECTS, set to 0.0")

    return result


@async_api_view(["GET"])
async def get_grades(request):
    term_id = request.GET.get("term_id")
    request_user = request.user

    if not request_user.usos_id:
        return Response({"detail": "User does not have a linked USOS account."}, status=400)
    try:
        async with USOSClient(USOS_BASE_URL, CONSUMER_KEY, CONSUMER_SECRET, trust_env=True) as client:
            client.load_access_token(request_user.access_token, request_user.access_token_secret)

            # Use safe wrapper instead of direct call
            ects = await get_user_courses_ects_safe(client)

            if not ects:
                return Response({"detail": "No ECTS data found for this user."}, status=404)

            # Check if terms are already in the database
            term_ids = ects.keys()
            existing_terms = Term.objects.filter(id__in=ects.keys())
            existing_term_ids = [term_id async for term_id in existing_terms.values_list("id", flat=True)]

            # Find missing terms
            missing_term_ids = set(term_ids) - set(existing_term_ids)

            # Get terms from the database
            terms = [term async for term in existing_terms.aiterator()]

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
            grades = await client.grade_service.get_grades_by_terms(term_id or [term.id for term in terms])

        courses_ects = {
            course: ects_points for term_courses in ects.values() for course, ects_points in term_courses.items()
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
                            "finish_date": term.finish_date,
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
                            for grade in grades.get(course_edition.term_id, {})
                            .get(course_edition.course_id, {})
                            .get("course_grades", [])
                        ],
                        "passing_status": course_edition.passing_status,
                    }
                    for course_edition in course_editions
                ],
            }
        )
    except APIException as e:
        logger.error(
            f"API error occurred for user {request_user.id}: {str(e)}",
            exc_info=True,
            extra={"user_id": request_user.id, "term_id": term_id},
        )
        return Response({"detail": "API error"}, status=500)
    except Exception as e:
        logger.error(
            f"Unexpected error occurred for user {request_user.id}: {str(e)}",
            exc_info=True,
            extra={"user_id": request_user.id, "term_id": term_id},
        )
        return Response({"detail": "An unexpected error occurred"}, status=500)
