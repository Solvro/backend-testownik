import os
import dotenv
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
import json
import requests
from django_ratelimit.decorators import ratelimit

dotenv.load_dotenv()

N8N_WEBHOOK = os.getenv("N8N_WEBHOOK")
FEEDBACK_SECRET = os.getenv("FEEDBACK_SECRET")


@api_view(["POST"])
@permission_classes([AllowAny])
@ratelimit(key="ip", rate="3/m", method="POST", block=True)
def feedback_add(request):
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
            print(f"Error while sending feedback form: {response.status_code}, {response.text}")
            return Response({"error": "Error while sending feedback form"}, status=500)

    except Exception as e:
        return Response({"error": f"Internal Server Error: {str(e)}"}, status=500)
