from django.shortcuts import HttpResponse
from maintenance.models import MaintenanceMode


class MaintenanceModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
            return self.get_response(request)

        if request.path.startswith('/admin/') or request.path.startswith('/login/usos') or request.path.startswith('/authorize/'):
            return self.get_response(request)

        toggle = MaintenanceMode.objects.first()
        if toggle and toggle.is_active:
            return HttpResponse("Service unavailable", status=503)

        return self.get_response(request)