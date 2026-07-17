import logging
import os

import dotenv
import requests
from adrf.generics import GenericAPIView
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from feedback.serializers import FeedbackSerializer

dotenv.load_dotenv()

logger = logging.getLogger(__name__)

N8N_WEBHOOK = os.getenv("N8N_WEBHOOK")
FEEDBACK_SECRET = os.getenv("FEEDBACK_SECRET")


class FeedbackAddView(GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = FeedbackSerializer

    @method_decorator(ratelimit(key="ip", rate="3/m", method="POST", block=True))
    @extend_schema(
        summary="Submit feedback",
        responses={
            200: OpenApiResponse(
                response={
                    "type": "object",
                    "properties": {"success": {"type": "string"}},
                },
                description="Feedback submitted successfully",
            ),
            400: OpenApiResponse(description="Missing required fields or invalid input"),
            500: OpenApiResponse(description="Internal server error or webhook failure"),
        },
    )
    def post(self, request):
        serializer = self.get_serializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        if N8N_WEBHOOK is None:
            raise APIException("Webhook not configured")

        try:
            payload = serializer.validated_data
            payload["secret"] = FEEDBACK_SECRET

            response = requests.post(N8N_WEBHOOK, data=payload)

            if response.ok:
                return Response({"success": "Feedback sent successfully"})
            else:
                logger.error(
                    "Error while sending feedback form: %s, %s",
                    response.status_code,
                    response.text,
                )
                raise APIException("Error while sending feedback form")

        except Exception as e:
            logger.exception("Unexpected error in feedback endpoint: %s", str(e))
            raise APIException("Internal Server Error")
