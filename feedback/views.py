import json
import os

import dotenv
import requests
from django_ratelimit.decorators import ratelimit
from drf_spectacular.utils import OpenApiResponse, OpenApiExample, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

dotenv.load_dotenv()

N8N_WEBHOOK = os.getenv("N8N_WEBHOOK")
FEEDBACK_SECRET = os.getenv("FEEDBACK_SECRET")


class FeedbackAddView(APIView):
    permission_classes = [AllowAny]

    @ratelimit(key="ip", rate="3/m", method="POST", block=True)
    @extend_schema(
        summary="Submit feedback",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["name", "title", "content"],
            }
        },
        responses={
            200: OpenApiResponse(
                response={"type": "object", "properties": {"success": {"type": "string"}}},
                description="Feedback submitted successfully",
            ),
            400: OpenApiResponse(description="Missing required fields or invalid input"),
            500: OpenApiResponse(description="Internal server error or webhook failure"),
        },
        examples=[
            OpenApiExample(
                "Feedback Example",
                value={
                    "name": "John Doe",
                    "title": "Bug in quiz system",
                    "content": "The scoring logic failed when I refreshed the page.",
                },
                request_only=True,
                status_codes=["200"],
            )
        ]
    )
    def post(self, request):
        try:
            data = json.loads(request.body)
            if not data:
                return Response({"error": "No data provided"}, status=400)
            if "name" not in data:
                return Response({"error": "Name is required"}, status=400)
            if "title" not in data:
                return Response({"error": "Title is required"}, status=400)
            if "content" not in data:
                return Response({"error": "Content is required"}, status=400)

            data["secret"] = FEEDBACK_SECRET
            response = requests.post(N8N_WEBHOOK, data=data)

            if response.ok:
                print("Feedback sent successfully!")
                return Response({"success": "Feedback sent successfully"})
            else:
                print(
                    f"Error while sending feedback form: {response.status_code}, {response.text}"
                )
                return Response({"error": "Error while sending feedback form"}, status=500)

        except Exception as e:
            return Response({"error": f"Internal Server Error: {str(e)}"}, status=500)
