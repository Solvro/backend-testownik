from django.apps import AppConfig
from django.db import OperationalError, ProgrammingError


class MaintenanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'maintenance'

    def ready(self):
        try:    
            from .models import MaintenanceMode
            if not MaintenanceMode.objects.exists():
                MaintenanceMode.objects.get_or_create(is_active=False)
        except (OperationalError, ProgrammingError):
            pass