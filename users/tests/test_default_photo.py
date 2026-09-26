from django.test import SimpleTestCase, override_settings

from uploads.models import UploadedImage
from users.models import User
from users.serializers import UserSerializer


@override_settings(
    BACKEND_URL="https://api.example.com",
    MEDIA_URL="/media/",
    STORAGES={"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"}},
)
class DefaultPhotoSerializerTests(SimpleTestCase):
    def test_original_photo_is_available_without_removing_custom_photo(self):
        original = UploadedImage(image="avatars/original.jpg")
        custom = UploadedImage(image="avatars/custom.jpg")
        user = User(email="preview@example.com", photo_image=original, custom_photo_image=custom)

        data = UserSerializer(user).data

        self.assertEqual(data["default_photo"], "https://api.example.com/media/avatars/original.jpg")
        self.assertEqual(data["photo"], "https://api.example.com/media/avatars/custom.jpg")
        self.assertTrue(data["has_custom_photo"])
        self.assertIs(user.custom_photo_image, custom)

    def test_no_original_photo_returns_null_even_with_legacy_custom_photo(self):
        user = User(email="preview@example.com", overriden_photo_url="https://example.com/custom.png")
        data = UserSerializer(user).data
        self.assertIsNone(data["default_photo"])
        self.assertEqual(data["photo"], user.overriden_photo_url)

    def test_legacy_account_photo_is_used_until_image_sync(self):
        user = User(email="preview@example.com", overriden_photo_url="https://example.com/custom.png")
        user.photo_url = "https://example.com/original.jpg"
        self.assertEqual(UserSerializer(user).data["default_photo"], user.photo_url)

    @override_settings(MEDIA_URL="https://cdn.example.com/media/")
    def test_absolute_storage_url_is_preserved(self):
        user = User(email="preview@example.com", photo_image=UploadedImage(image="avatars/original.jpg"))
        self.assertEqual(
            UserSerializer(user).data["default_photo"],
            "https://cdn.example.com/media/avatars/original.jpg",
        )

    def test_default_photo_is_read_only(self):
        serializer = UserSerializer(
            User(email="preview@example.com"), data={"default_photo": "https://example.com/new.jpg"}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn("default_photo", serializer.validated_data)
