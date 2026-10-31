from django.apps import AppConfig
from django.core.validators import MaxLengthValidator


class OAuthIntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "oauth_integrations"

    def ready(self):
        from oauth2_provider.models import get_application_model

        client_id_field = get_application_model()._meta.get_field("client_id")
        # Native CIMD uses full metadata URLs as client IDs; the toolkit defaults to 255.
        client_id_field.max_length = 2048
        client_id_field.validators = [
            validator for validator in client_id_field.validators if not isinstance(validator, MaxLengthValidator)
        ] + [MaxLengthValidator(2048)]
