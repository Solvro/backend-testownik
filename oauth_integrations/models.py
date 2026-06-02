from django.db import models


class OAuthClientMetadata(models.Model):
    application = models.OneToOneField(
        "oauth2_provider.Application",
        on_delete=models.CASCADE,
        related_name="cimd_metadata",
        swappable=False,
    )
    client_id_url = models.URLField(max_length=2048, unique=True)
    client_name = models.CharField(max_length=255)
    client_uri = models.URLField(max_length=2048, blank=True)
    logo_uri = models.URLField(max_length=2048, blank=True)
    redirect_uris = models.JSONField(default=list)
    grant_types = models.JSONField(default=list)
    response_types = models.JSONField(default=list)
    token_endpoint_auth_method = models.CharField(max_length=64, default="none")
    metadata = models.JSONField(default=dict)
    fetched_at = models.DateTimeField()
    cache_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "OAuth client metadata"
        verbose_name_plural = "OAuth client metadata"

    def __str__(self):
        return self.client_name or self.client_id_url
