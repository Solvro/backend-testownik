from constance import config
from django.http import JsonResponse
from django.shortcuts import HttpResponse


class MaintenanceModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
            return self.get_response(request)

        if (
            request.path.startswith("/admin/")
            or request.path.startswith("/login/")
            or request.path.startswith("/authorize/")
        ):
            return self.get_response(request)

        if config.MAINTENANCE_MODE:
            if request.headers.get("Content-Type") == "text/plain":
                return JsonResponse({"detail": "Service is unavailable"}, status=503)
            return HttpResponse("Service unavailable", status=503)

        return self.get_response(request)
