import os

import requests
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Download the latest base email template from GitHub and replace the local one"

    def handle(self, *args, **options):
        download_url = "https://github.com/Solvro/emails-testownik/releases/latest/download/base.html"

        try:
            response = requests.get(download_url)
            response.raise_for_status()
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f"Failed to download base.html: {e}"))
            return

        template_path = os.path.join(settings.BASE_DIR, "templates", "emails", "base.html")

        try:
            with open(template_path, "w", encoding="utf-8") as f:
                f.write(response.text)
            self.stdout.write(self.style.SUCCESS("Successfully updated base.html template"))
        except OSError as e:
            self.stderr.write(self.style.ERROR(f"Failed to write to file: {e}"))
