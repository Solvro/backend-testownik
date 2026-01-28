import logging

from django.core.exceptions import ValidationError
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import UploadedImage
from .serializers import UploadedImageSerializer
from .utils import process_uploaded_image

logger = logging.getLogger(__name__)


class ImageUploadView(APIView):
    """
    API endpoint for uploading images.

    Accepts multipart/form-data with 'image' field.
    Validates, resizes (if needed), converts to AVIF, and stores the image.
    Returns metadata including the URL for use in questions/answers.
    """

    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Upload an image",
        description=(
            "Uploads an image file (max 5MB). Supported formats: JPEG, PNG, GIF, WEBP, AVIF. "
            "Images larger than 1920px are automatically resized. "
            "Static images are converted to AVIF. "
            "Animated GIFs are preserved in original format. "
            "Returns the image UUID and URL for use in question/answer creation."
        ),
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "image": {
                        "type": "string",
                        "format": "binary",
                        "description": "Image file (JPEG, PNG, GIF, WEBP, or AVIF)",
                    }
                },
                "required": ["image"],
            }
        },
        responses={
            201: UploadedImageSerializer,
            400: OpenApiResponse(description="Invalid file, unsupported format, or size limit exceeded"),
            401: OpenApiResponse(description="Authentication required"),
        },
        tags=["uploads"],
    )
    def post(self, request, *args, **kwargs):
        if "image" not in request.FILES:
            return Response(
                {"error": "No image file provided. Use 'image' field in multipart form data."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        image_file = request.FILES["image"]

        try:
            processed_file, width, height, content_type = process_uploaded_image(image_file)
        except ValidationError as e:
            logger.warning(
                "Image validation failed for user %s: %s - %s",
                request.user.id,
                image_file.name,
                str(e),
            )
            return Response({"error": str(e.message)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception(
                "Image processing failed for user %s: %s",
                request.user.id,
                image_file.name,
            )
            return Response(
                {"error": "Image processing failed. Please try a different file."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_image = UploadedImage.objects.create(
            image=processed_file,
            original_filename=image_file.name[:255],
            content_type=content_type,
            file_size=processed_file.size,
            width=width,
            height=height,
            uploaded_by=request.user,
        )

        serializer = UploadedImageSerializer(uploaded_image, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
