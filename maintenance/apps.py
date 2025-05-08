from django.apps import AppConfig


class MaintenanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'maintenance'

    def ready(self):
        from .models import MaintenanceMode
        if not MaintenanceMode.objects.exists():
            MaintenanceMode.objects.create(is_active=False)