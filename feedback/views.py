import os
import dotenv
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
import json
import requests
from django_ratelimit.decorators import ratelimit

dotenv.load_dotenv()

FORM_LINK = os.getenv("FORM_LINK")
NAME_INPUT = os.getenv("NAME_INPUT")
EMAIL_INPUT = os.getenv("EMAIL_INPUT")
CONTENT_INPUT = os.getenv("CONTENT_INPUT")


@api_view(["POST"])
@permission_classes([AllowAny])
@ratelimit(key="ip", rate="5/m", method="POST", block=True)
def feedback_add(request):
    try:
        data = json.loads(request.body)
        if not data:
            return Response({"error": "No data provided"}, status=400)
        if "name" not in data:
            return Response({"error": "Email is required"}, status=400)
        if "content" not in data:
            return Response({"error": "Text is required"}, status=400)

        form_data = {
            NAME_INPUT: data["name"],
            EMAIL_INPUT: data["email"],
            CONTENT_INPUT: data["content"],
        }
        response = requests.post(FORM_LINK, data=form_data)

        if response.ok:
            print("Feedback sent successfully!")
            return Response({"success": "Feedback sent successfully"})
        else:
            print(f"Error while sending feedback form: {response.status_code}, {response.text}")
            return Response({"error": "Error while sending feedback form"}, status=500)

    except Exception as e:
        return Response({"error": f"Internal Server Error: {str(e)}"}, status=500)
