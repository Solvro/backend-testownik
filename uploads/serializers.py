from rest_framework import serializers

from .models import UploadedImage


class UploadedImageSerializer(serializers.ModelSerializer):
    """Serializer for uploaded image responses."""

    url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = UploadedImage
        fields = [
            "id",
            "url",
            "original_filename",
            "content_type",
            "file_size",
            "width",
            "height",
            "uploaded_at",
        ]
        read_only_fields = fields

    def get_url(self, obj):
        """Return absolute URL for the image."""
        request = self.context.get("request")
        if obj.image:
            url = obj.image.url
            if request is not None:
                return request.build_absolute_uri(url)
            return url
        return None
