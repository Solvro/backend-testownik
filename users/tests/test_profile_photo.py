"""Tests for profile photo feature: model property, upload/delete endpoint, SSRF validation."""

import io
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image as PILImage
from rest_framework import status
from rest_framework.test import APITestCase

from uploads.models import UploadedImage
from uploads.utils import validate_image_source_url
from users.models import User
from users.serializers import UserSerializer

PHOTO_TEST_STORAGE = {"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"}}


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


@override_settings(STORAGES=PHOTO_TEST_STORAGE)
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


@override_settings(STORAGES=PHOTO_TEST_STORAGE)
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
        self.assertTrue(response.data["has_custom_photo"])
        self.assertTrue(response.data["photo"])

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

    def test_guest_cannot_upload_or_reset(self):
        self.user.account_type = "guest"
        self.user.save(update_fields=["account_type"])
        self.assertEqual(self.client.post(self.url, {"photo": _create_test_image_file()}).status_code, 403)
        self.assertEqual(self.client.delete(self.url).status_code, 403)

    def test_reset_clears_legacy_photo_and_does_not_resurrect_in_backfill(self):
        self.user.overriden_photo_url = "https://api.dicebear.com/9.x/micah/svg?seed=legacy"
        self.user.save(update_fields=["overriden_photo_url"])
        self.assertEqual(self.user.photo, self.user.overriden_photo_url)
        self.assertTrue(UserSerializer(self.user).data["has_custom_photo"])
        response = self.client.delete(self.url)
        self.assertFalse(response.data["has_custom_photo"])
        with patch("users.management.commands.backfill_user_photos.download_image_source") as download:
            call_command("backfill_user_photos", stdout=io.StringIO())
        download.assert_not_called()

    def test_replacement_and_reset_leave_only_unreferenced_images_for_cleanup(self):
        self.client.post(self.url, {"photo": _create_test_image_file()})
        self.user.refresh_from_db()
        old = self.user.custom_photo_image
        self.client.post(self.url, {"photo": _create_test_image_file()})
        self.user.refresh_from_db()
        current = self.user.custom_photo_image
        self.assertTrue(old.is_orphan)
        self.assertFalse(current.is_orphan)
        self.client.delete(self.url)
        self.assertTrue(current.is_orphan)


class ValidateImageSourceUrlTests(TestCase):
    """Tests for validate_image_source_url allowlist-based SSRF protection."""

    ALLOWED = ["example.com", "api.dicebear.com", "apps.usos.pwr.edu.pl"]

    def test_allows_known_host_https(self):
        validate_image_source_url("https://example.com/photo.jpg", allowed_hosts=self.ALLOWED)

    def test_allows_known_host_http(self):
        validate_image_source_url("http://example.com/photo.jpg", allowed_hosts=self.ALLOWED)

    def test_rejects_unknown_host(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("https://evil.com/photo.jpg", allowed_hosts=self.ALLOWED)

    def test_rejects_ftp_url(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("ftp://example.com/photo.jpg", allowed_hosts=self.ALLOWED)

    def test_rejects_file_url(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("file:///etc/passwd", allowed_hosts=self.ALLOWED)

    def test_rejects_data_url(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("data:image/png;base64,abc123", allowed_hosts=self.ALLOWED)

    def test_rejects_empty_url(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("", allowed_hosts=self.ALLOWED)

    def test_rejects_host_not_in_allowlist(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("http://127.0.0.1:8000/photo.jpg", allowed_hosts=self.ALLOWED)

    def test_rejects_url_without_hostname(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("http:///path/to/file", allowed_hosts=self.ALLOWED)

    def test_rejects_no_allowed_hosts_configured(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("https://example.com/photo.jpg", allowed_hosts=[])

    @override_settings(ALLOWED_IMAGE_SOURCE_HOSTS=["test.pwr.edu.pl"])
    def test_reads_allowed_hosts_from_settings(self):
        validate_image_source_url("https://test.pwr.edu.pl/photo.jpg")

    @override_settings(ALLOWED_IMAGE_SOURCE_HOSTS=[])
    def test_rejects_when_settings_empty(self):
        with self.assertRaises(ValidationError):
            validate_image_source_url("https://test.pwr.edu.pl/photo.jpg")

    def test_allows_dicebear_host(self):
        validate_image_source_url(
            "https://api.dicebear.com/9.x/adventurer/png?seed=test@example.com",
            allowed_hosts=["api.dicebear.com"],
        )

    def test_allows_usos_host(self):
        validate_image_source_url(
            "https://apps.usos.pwr.edu.pl/photo/user123.jpg",
            allowed_hosts=["apps.usos.pwr.edu.pl"],
        )


@override_settings(STORAGES=PHOTO_TEST_STORAGE)
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


@override_settings(STORAGES=PHOTO_TEST_STORAGE)
class PhotoWorkerTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="worker@example.com", password="test")

    def test_enqueue_waits_for_commit_and_worker_persists_photo(self):
        from django_tasks_db.models import DBTaskResult

        from users.views.oauth import enqueue_user_photo

        image = _create_test_image_file()
        with patch("users.views.oauth._sync_download_photo", return_value=(image.read(), "image/jpeg")) as download:
            with transaction.atomic():
                enqueue_user_photo(self.user.id, "https://api.dicebear.com/9.x/micah/png?seed=test")
                self.assertFalse(DBTaskResult.objects.exists())
            download.assert_not_called()
            self.assertEqual(DBTaskResult.objects.get().status, "READY")
            call_command(
                "db_worker",
                "--backend=images",
                queue_name="images",
                batch=True,
                reload=False,
                startup_delay=False,
                verbosity=0,
            )
        self.assertEqual(DBTaskResult.objects.get().status, "SUCCESSFUL")
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.photo_image_id)

    def test_rollback_does_not_enqueue(self):
        from django_tasks_db.models import DBTaskResult

        from users.views.oauth import enqueue_user_photo

        with transaction.atomic():
            enqueue_user_photo(self.user.id, "https://api.dicebear.com/photo.png")
            transaction.set_rollback(True)
        self.assertFalse(DBTaskResult.objects.exists())

    def test_queue_failure_does_not_fail_login(self):
        from users.views.oauth import enqueue_user_photo

        with patch("django_tasks_db.DatabaseBackend.enqueue", side_effect=RuntimeError("unavailable")):
            enqueue_user_photo(self.user.id, "https://api.dicebear.com/photo.png")

    def test_worker_records_failure_without_sensitive_exception_text(self):
        from django_tasks_db.models import DBTaskResult

        from users.tasks import sync_user_photo_task

        sync_user_photo_task.enqueue(str(self.user.id), "https://api.dicebear.com/photo.png")
        with patch("users.views.oauth._sync_download_photo", side_effect=ValueError("seed=private@example.com")):
            call_command(
                "db_worker",
                "--backend=images",
                queue_name="images",
                batch=True,
                reload=False,
                startup_delay=False,
                verbosity=0,
            )
        result = DBTaskResult.objects.get()
        self.assertEqual(result.status, "FAILED")
        self.assertNotIn("private@example.com", result.traceback)


@override_settings(STORAGES=PHOTO_TEST_STORAGE)
class PhotoBackfillTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="legacy@example.com",
            password="test",
            overriden_photo_url="https://api.dicebear.com/9.x/micah/svg?seed=legacy@example.com",
        )

    def test_backfill_rasterizes_dicebear_is_idempotent_and_redacts_filename(self):
        image = _create_test_image_file()
        with patch(
            "users.management.commands.backfill_user_photos.Command._download",
            return_value=(image.read(), "image/jpeg"),
        ) as download:
            call_command("backfill_user_photos", stdout=io.StringIO())
            call_command("backfill_user_photos", stdout=io.StringIO())
        download.assert_called_once_with("https://api.dicebear.com/9.x/micah/png?seed=legacy@example.com", 5)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.overriden_photo_url)
        self.assertIsNotNone(self.user.custom_photo_image_id)
        self.assertNotIn("legacy@example.com", self.user.custom_photo_image.original_filename)

    def test_backfill_does_not_overwrite_concurrent_reset(self):
        from users.management.commands.backfill_user_photos import Command

        image = _create_test_image_file()

        def download(*args):
            User.objects.filter(pk=self.user.pk).update(overriden_photo_url=None)
            return image.read(), "image/jpeg"

        with patch.object(Command, "_download", side_effect=download):
            self.assertEqual(Command()._process_user(self.user, timeout=5, dry_run=False), "skip")
        self.user.refresh_from_db()
        self.assertIsNone(self.user.custom_photo_image_id)
        self.assertFalse(UploadedImage.objects.exists())

    def test_backfill_and_worker_preserve_avif_filename(self):
        from users.management.commands.backfill_user_photos import Command
        from users.views.oauth import _process_and_save_photo_file

        image = _create_test_image_file(format="AVIF")
        raw_content = image.read()
        url = "https://api.dicebear.com/photo.AVIF?seed=private@example.com#fragment"
        saved = Command()._save_image(self.user, url, raw_content, "image/avif")
        self.assertEqual(saved.original_filename, "photo.AVIF")
        _process_and_save_photo_file(self.user, url, raw_content, "image/avif")
        self.user.refresh_from_db()
        self.assertEqual(self.user.photo_image.original_filename, "photo.AVIF")
