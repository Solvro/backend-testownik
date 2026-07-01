from django.apps import AppConfig


class WrappedConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wrapped"
    verbose_name = "Testownik Wrapped"
