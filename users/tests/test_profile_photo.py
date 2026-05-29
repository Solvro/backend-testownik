"""Tests for profile photo feature: model property, upload/delete endpoint, SSRF validation."""

import io
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image as PILImage
from rest_framework import status
from rest_framework.test import APITestCase

from uploads.models import UploadedImage
from uploads.utils import validate_image_source_url
from users.models import User
from users.serializers import UserSerializer


def _create_test_image_file(format: str = "JPEG", size: tuple = (100, 100)) -> SimpleUploadedFile:
    """Create a small test image in memory and return as SimpleUploadedFile."""
    buf = io.BytesIO()
    img = PILImage.new("RGB", size, color="red")
    img.save(buf, format=format)
    buf.seek(0)
    ext = format.lower().replace("jpeg", "jpg")
    return SimpleUploadedFile(
        name=f"test.{ext}",
        content=buf.read(),
        content_type=f"image/{format.lower().replace('jpeg', 'jpeg')}",
    )


class UserPhotoModelPropertyTests(TestCase):
    """Tests for User.photo property."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="photo-test@example.com",
            password="password123",
            first_name="Photo",
            last_name="Test",
        )

    def test_photo_returns_none_when_no_images(self):
        self.assertIsNone(self.user.photo)

    def test_photo_returns_photo_image_url(self):
        uploaded = UploadedImage.objects.create(
            image=_create_test_image_file(),
            original_filename="usos_photo.jpg",
            content_type="image/jpeg",
            file_size=100,
            width=100,
            height=100,
            uploaded_by=self.user,
        )
        self.user.photo_image = uploaded
        self.user.save(update_fields=["photo_image"])

        photo_url = self.user.photo
        self.assertIsNotNone(photo_url)
        self.assertIn(uploaded.image.name, photo_url)

    def test_photo_prefers_custom_over_usos(self):
        usos_photo = UploadedImage.objects.create(
            image=_create_test_image_file(),
            original_filename="usos.jpg",
            content_type="image/jpeg",
            file_size=100,
            width=100,
            height=100,
            uploaded_by=self.user,
        )
        custom_photo = UploadedImage.objects.create(
            image=_create_test_image_file(),
            original_filename="custom.jpg",
            content_type="image/jpeg",
            file_size=100,
            width=100,
            height=100,
            uploaded_by=self.user,
        )
        self.user.photo_image = usos_photo
        self.user.custom_photo_image = custom_photo
        self.user.save(update_fields=["photo_image", "custom_photo_image"])

        photo_url = self.user.photo
        self.assertIn(custom_photo.image.name, photo_url)

    @override_settings(BACKEND_URL="https://api.example.com")
    def test_photo_makes_relative_url_absolute(self):
        uploaded = UploadedImage.objects.create(
            image=_create_test_image_file(),
            original_filename="test.jpg",
            content_type="image/jpeg",
            file_size=100,
            width=100,
            height=100,
            uploaded_by=self.user,
        )
        self.user.photo_image = uploaded
        self.user.save(update_fields=["photo_image"])

        photo_url = self.user.photo
        self.assertTrue(photo_url.startswith("https://api.example.com/"))

    def test_has_custom_photo_serializer_field(self):
        serializer = UserSerializer(self.user)
        self.assertFalse(serializer.data["has_custom_photo"])

        custom = UploadedImage.objects.create(
            image=_create_test_image_file(),
            original_filename="custom.jpg",
            content_type="image/jpeg",
            file_size=100,
            width=100,
            height=100,
            uploaded_by=self.user,
        )
        self.user.custom_photo_image = custom
        self.user.save(update_fields=["custom_photo_image"])

        serializer = UserSerializer(self.user)
        self.assertTrue(serializer.data["has_custom_photo"])


class UserPhotoUploadEndpointTests(APITestCase):
    """Tests for POST/DELETE /api/user/photo/."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="upload-test@example.com",
            password="password123",
            first_name="Upload",
            last_name="Test",
        )
        self.client.force_authenticate(user=self.user)
        self.url = reverse("api_user_photo")

    def test_upload_valid_image(self):
        image = _create_test_image_file()
        response = self.client.post(self.url, {"photo": image}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)

        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.custom_photo_image)
        self.assertTrue(self.user.custom_photo_image.content_type.startswith("image/"))

    def test_upload_without_photo_returns_400(self):
        response = self.client.post(self.url, {}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_upload_non_image_file_returns_400(self):
        bogus = SimpleUploadedFile("test.txt", b"not an image", content_type="text/plain")
        response = self.client.post(self.url, {"photo": bogus}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_upload_excessively_large_file_returns_400(self):
        large_content = b"x" * (11 * 1024 * 1024)  # 11MB
        large_file = SimpleUploadedFile("large.jpg", large_content, content_type="image/jpeg")
        response = self.client.post(self.url, {"photo": large_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_custom_photo(self):
        # First upload
        image = _create_test_image_file()
        self.client.post(self.url, {"photo": image}, format="multipart")
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.custom_photo_image)

        # Then delete
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertIsNone(self.user.custom_photo_image)

    def test_unauthenticated_user_cannot_upload(self):
        self.client.force_authenticate(user=None)
        image = _create_test_image_file()
        response = self.client.post(self.url, {"photo": image}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_user_cannot_delete(self):
        self.client.force_authenticate(user=None)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ValidateImageSourceUrlTests(TestCase):
    """Tests for validate_image_source_url SSRF protection."""

    def test_allows_https_url(self):
        validate_image_source_url("https://example.com/photo.jpg")

    def test_allows_http_url(self):
        validate_image_source_url("http://example.com/photo.jpg")

    def test_rejects_ftp_url(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("ftp://example.com/photo.jpg")

    def test_rejects_file_url(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("file:///etc/passwd")

    def test_rejects_data_url(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("data:image/png;base64,abc123")

    def test_rejects_empty_url(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("")

    def test_rejects_loopback_ip(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("http://127.0.0.1:8000/photo.jpg")

    def test_rejects_private_ip_10_dot(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("http://10.0.0.1/photo.jpg")

    def test_rejects_private_ip_192_dot(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("http://192.168.1.1/photo.jpg")

    def test_rejects_link_local(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("http://169.254.169.254/latest/meta-data/")

    @patch("uploads.utils.socket.getaddrinfo")
    def test_rejects_hostname_resolving_to_private_ip(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (0, 0, 0, "", ("10.0.0.1", 80)),
        ]
        with self.assertRaises(ValidationError):
            validate_image_source_url("http://internal-secret.example.com/photo.jpg")

    def test_rejects_url_without_hostname(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("http:///path/to/file")


class PublicUserPhotoFieldTests(APITestCase):
    """Tests that PublicUserSerializer exposes photo field correctly."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="public-photo@example.com",
            password="password123",
            first_name="Public",
            last_name="Photo",
        )
        uploaded = UploadedImage.objects.create(
            image=_create_test_image_file(),
            original_filename="profile.jpg",
            content_type="image/jpeg",
            file_size=100,
            width=100,
            height=100,
            uploaded_by=self.user,
        )
        self.user.photo_image = uploaded
        self.user.save(update_fields=["photo_image"])

    def test_public_user_serializer_includes_photo(self):
        from users.serializers import PublicUserSerializer

        serializer = PublicUserSerializer(self.user)
        self.assertIn("photo", serializer.data)
        self.assertIsNotNone(serializer.data["photo"])

    def test_public_user_list_includes_photo(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("user-list")
        response = self.client.get(url, {"search": "Public"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if response.data:
            self.assertIn("photo", response.data[0])
