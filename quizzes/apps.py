from django.apps import AppConfig


class QuizzesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "quizzes"

    def ready(self):
        from .signals import register_signals

        register_signals()
