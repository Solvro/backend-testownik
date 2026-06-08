from urllib.parse import urljoin

from django.apps import AppConfig
from django.conf import settings
from django.templatetags.static import static


class TestownikCoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "testownik_core"

    def ready(self):
        from mcp.types import Icon
        from mcp_server.djangomcp import global_mcp_server

        def absolute_static_url(path):
            url = static(path)
            if url.startswith(("http://", "https://", "data:")):
                return url
            return urljoin(settings.OAUTH_ISSUER_URL.rstrip("/") + "/", url)

        global_mcp_server._mcp_server.icons = [
            Icon(
                src=absolute_static_url("logo.svg"),
                mimeType="image/svg+xml",
                sizes=["any"],
                theme="light",
            ),
            Icon(
                src=absolute_static_url("logo-dark.svg"),
                mimeType="image/svg+xml",
                sizes=["any"],
                theme="dark",
            ),
        ]
        global_mcp_server._mcp_server.website_url = settings.FRONTEND_URL
