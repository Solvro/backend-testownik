from django.core.management.base import BaseCommand, CommandError
from oauth2_provider.models import get_application_model


class Command(BaseCommand):
    help = "Register the first-party public mobile OAuth client (authorization code + PKCE)."

    def handle(self, *args, **options):
        Application = get_application_model()
        app, created = Application.objects.get_or_create(
            client_id="testownik-mobile",
            defaults={
                "name": "Testownik Mobile",
                "client_type": Application.CLIENT_PUBLIC,
                "authorization_grant_type": Application.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "testownik://auth",
                "client_secret": "",
                "skip_authorization": False,
            },
        )
        if not created and (
            app.client_type != Application.CLIENT_PUBLIC
            or app.authorization_grant_type != Application.GRANT_AUTHORIZATION_CODE
            or app.redirect_uris != "testownik://auth"
        ):
            raise CommandError("Existing mobile registration differs; inspect it before changing its access.")
        self.stdout.write(
            "Mobile public OAuth client registered." if created else "Mobile OAuth client already registered."
        )
