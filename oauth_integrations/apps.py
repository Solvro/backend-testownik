from django.apps import AppConfig
from django.core.validators import MaxLengthValidator


class OAuthIntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "oauth_integrations"

    def ready(self):
        from django.db.models.signals import post_save
        from oauth2_provider.models import get_application_model

        from oauth_integrations.cimd_metadata_fetcher import persist_validated_cimd_metadata

        client_id_field = get_application_model()._meta.get_field("client_id")
        # Native CIMD uses full metadata URLs as client IDs; the toolkit defaults to 255.
        client_id_field.max_length = 2048
        client_id_field.validators = [
            validator for validator in client_id_field.validators if not isinstance(validator, MaxLengthValidator)
        ] + [MaxLengthValidator(2048)]

        post_save.connect(
            persist_validated_cimd_metadata,
            sender=get_application_model(),
            dispatch_uid="oauth_integrations.persist_validated_cimd_metadata",
        )
