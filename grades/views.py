import logging
import os

import dotenv
from adrf.decorators import api_view as async_api_view
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from usos_api import USOSClient

from grades.class_types import get_class_types
from grades.grade_reports import GRADE_REPORT_FIELDS, serialize_courses, term_stats
from grades.terms import get_terms

dotenv.load_dotenv()

logger = logging.getLogger(__name__)

USOS_BASE_URL = "https://apps.usos.pwr.edu.pl/"
CONSUMER_KEY = os.getenv("USOS_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("USOS_CONSUMER_SECRET")


@async_api_view(["GET"])
async def get_grades(request):
    selected_term_id = request.GET.get("term_id")
    request_user = request.user

    if not request_user.usos_id:
        return Response({"detail": "User does not have a linked USOS account."}, status=400)
    try:
        async with USOSClient(USOS_BASE_URL, CONSUMER_KEY, CONSUMER_SECRET, trust_env=True) as client:
            client.load_access_token(request_user.access_token, request_user.access_token_secret)
            class_types_by_id = await get_class_types()

            requested_term_ids = [selected_term_id] if selected_term_id else None
            ects_by_term, reports_by_term = await client.helper.get_user_exam_reports_with_ects(
                term_ids=requested_term_ids,
                fields=GRADE_REPORT_FIELDS,
            )
            term_ids = requested_term_ids or list(ects_by_term.keys())
            if not term_ids:
                return Response({"detail": "No grade data found for this user."}, status=404)

            if not reports_by_term:
                return Response({"detail": "No grade data found for this user."}, status=404)

            terms = await get_terms(term_ids)

        serialized_grades = serialize_courses(
            reports_by_term=reports_by_term,
            ects_by_term=ects_by_term,
            term_ids=term_ids,
            class_types_by_id=class_types_by_id,
        )
        grades_by_term = serialized_grades["grades_by_term"]

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
                            **term_stats(grades_by_term.get(term.id, [])),
                        }
                        for term in terms
                    ],
                    key=lambda term: term["start_date"],
                    reverse=True,
                ),
                "courses": serialized_grades["courses"],
            }
        )
    except APIException as e:
        logger.error(
            f"API error occurred for user {request_user.id}: {str(e)}",
            exc_info=True,
            extra={"user_id": request_user.id, "term_id": selected_term_id},
        )
        return Response({"detail": "API error"}, status=500)
    except Exception as e:
        logger.error(
            f"Unexpected error occurred for user {request_user.id}: {str(e)}",
            exc_info=True,
            extra={"user_id": request_user.id, "term_id": selected_term_id},
        )
        return Response({"detail": "An unexpected error occurred"}, status=500)
