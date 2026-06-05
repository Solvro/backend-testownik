from django.contrib import admin
from unfold.admin import ModelAdmin

from oauth_integrations.models import OAuthClientMetadata


@admin.register(OAuthClientMetadata)
class OAuthClientMetadataAdmin(ModelAdmin):
    list_display = ["client_name", "client_id_url", "application", "fetched_at", "cache_expires_at"]
    list_filter = ["fetched_at", "cache_expires_at", "token_endpoint_auth_method"]
    search_fields = ["client_name", "client_id_url", "client_uri"]
    readonly_fields = ["fetched_at", "cache_expires_at"]

    autocomplete_fields = ["application"]
