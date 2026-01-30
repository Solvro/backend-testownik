from datetime import timedelta
from io import BytesIO, StringIO

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Question, Quiz
from uploads.models import UploadedImage
from users.models import User


def create_image_file(width=100, height=100, format="JPEG", name="test.jpg"):
    """Create a test image file with configurable dimensions and format."""
    file = BytesIO()
    mode = "RGBA" if format in ("PNG", "WEBP") else "RGB"
    image = Image.new(mode, (width, height), "white")
    image.save(file, format)
    file.name = name
    file.seek(0)
    return file


def create_large_image_file():
    """Create an image larger than MAX_DIMENSION (1920px)."""
    return create_image_file(width=2500, height=2000, name="large.jpg")


def create_animated_gif():
    """Create a simple animated GIF with 2 frames."""
    file = BytesIO()
    frames = [
        Image.new("RGB", (50, 50), "red"),
        Image.new("RGB", (50, 50), "blue"),
    ]
    frames[0].save(file, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    file.name = "animated.gif"
    file.seek(0)
    return file


def create_oversized_file():
    """Create a file that exceeds the 10MB limit."""
    file = BytesIO()
    # Create a large uncompressed BMP-like data that will exceed 10MB
    # 11MB of random data
    file.write(b"\x00" * (11 * 1024 * 1024))
    file.name = "oversized.jpg"
    file.seek(0)
    return file


def create_unsupported_format_file():
    """Create a file with unsupported format (BMP)."""
    file = BytesIO()
    image = Image.new("RGB", (100, 100), "white")
    image.save(file, format="BMP")
    file.name = "test.bmp"
    file.seek(0)
    return file


def create_corrupted_image_file():
    """Create a file that looks like an image but is corrupted."""
    file = BytesIO()
    # Write some garbage data that's not a valid image
    file.write(b"This is not a valid image file content at all")
    file.name = "corrupted.jpg"
    file.seek(0)
    return file


# Use local filesystem storage for tests instead of S3
@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class UploadFlowTests(APITestCase):
    """Tests for the image upload workflow."""

    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="password")
        self.client.force_authenticate(user=self.user)
        self.upload_url = reverse("image-upload")

    def test_upload_image(self):
        """Test basic image upload returns correct response."""
        img = create_image_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("url", response.data)
        self.assertIn("id", response.data)
        self.assertIn("width", response.data)
        self.assertIn("height", response.data)
        self.assertIn("file_size", response.data)
        self.assertTrue(UploadedImage.objects.filter(id=response.data["id"]).exists())

    def test_upload_converts_to_avif(self):
        """Test that static images are converted to AVIF format."""
        img = create_image_file(format="JPEG", name="test.jpg")
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify stored as AVIF
        uploaded = UploadedImage.objects.get(id=response.data["id"])
        self.assertEqual(uploaded.content_type, "image/avif")
        self.assertTrue(uploaded.image.name.endswith(".avif"))

    def test_upload_png_converts_to_avif(self):
        """Test PNG images are converted to AVIF (preserving transparency)."""
        img = create_image_file(format="PNG", name="test.png")
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        uploaded = UploadedImage.objects.get(id=response.data["id"])
        self.assertEqual(uploaded.content_type, "image/avif")

    def test_upload_animated_gif_stays_gif(self):
        """Test that animated GIFs are NOT converted (kept as GIF)."""
        img = create_animated_gif()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Animated GIF should stay as GIF
        uploaded = UploadedImage.objects.get(id=response.data["id"])
        self.assertEqual(uploaded.content_type, "image/gif")
        self.assertTrue(uploaded.image.name.endswith(".gif"))

    def test_upload_large_image_gets_resized(self):
        """Test that images larger than 1920px are automatically resized."""
        img = create_large_image_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Should be resized to fit within 1920x1920
        self.assertLessEqual(response.data["width"], 1920)
        self.assertLessEqual(response.data["height"], 1920)

    def test_upload_without_auth_fails(self):
        """Test that unauthenticated users cannot upload."""
        self.client.force_authenticate(user=None)
        img = create_image_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_upload_no_file_fails(self):
        """Test that request without file returns error."""
        response = self.client.post(self.upload_url, {}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_upload_file_too_large(self):
        """Test that files exceeding size limit are rejected."""
        img = create_oversized_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertIn("too large", response.data["error"].lower())

    def test_upload_unsupported_format(self):
        """Test that unsupported file formats are rejected."""
        img = create_unsupported_format_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)
        self.assertIn("unsupported", response.data["error"].lower())

    def test_upload_corrupted_image(self):
        """Test that corrupted image files are rejected."""
        img = create_corrupted_image_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_link_image_to_question(self):
        """Test linking uploaded image to a question via API."""
        # 1. Upload
        img = create_image_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")
        image_id = response.data["id"]

        # 2. Create Quiz with Question using image_upload
        quiz = Quiz.objects.create(title="Test Quiz", maintainer=self.user)

        question_data = {"order": 1, "text": "Question with image", "image_upload": image_id, "answers": []}

        quiz_url = reverse("quiz-detail", args=[quiz.id])
        data = {"title": "UPDATED", "questions": [question_data]}

        response = self.client.put(quiz_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        question = Question.objects.get(quiz=quiz)
        self.assertEqual(str(question.image_upload.id), image_id)
        # Verify unified image property returns a URL containing the uploaded file path
        self.assertIsNotNone(question.image)
        self.assertIn("/media/images/", question.image)

    def test_link_external_url_to_question(self):
        """Test using external URL for question image."""
        quiz = Quiz.objects.create(title="Test Quiz", maintainer=self.user)
        external_url = "https://example.com/image.jpg"

        quiz_url = reverse("quiz-detail", args=[quiz.id])
        data = {
            "title": "Test",
            "questions": [
                {"order": 1, "text": "Question with external image", "image_url": external_url, "answers": []}
            ],
        }

        response = self.client.put(quiz_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        question = Question.objects.get(quiz=quiz)
        self.assertEqual(question.image_url, external_url)
        self.assertIsNone(question.image_upload)
        # Unified property should return external URL
        self.assertEqual(question.image, external_url)

    def test_copy_quiz_shares_image(self):
        """Test that copying a quiz shares the image reference (copy-on-write)."""
        # 1. Setup Quiz with image
        img = create_image_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")
        image_id = response.data["id"]
        upload_obj = UploadedImage.objects.get(id=image_id)

        quiz = Quiz.objects.create(title="Original", maintainer=self.user)
        q1 = Question.objects.create(quiz=quiz, order=1, text="Q1", image_upload=upload_obj)

        # 2. Copy the quiz
        copy_url = reverse("quiz-copy", args=[quiz.id])
        response = self.client.post(copy_url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        new_quiz_id = response.data["id"]
        new_quiz = Quiz.objects.get(id=new_quiz_id)
        new_q1 = new_quiz.questions.first()

        # 3. Verify copy-on-write behavior
        self.assertNotEqual(q1.id, new_q1.id)  # Different question
        self.assertEqual(new_q1.image_upload, upload_obj)  # Same image reference
        self.assertEqual(UploadedImage.objects.count(), 1)  # Still only 1 image file

    def test_cleanup_orphans(self):
        """Test that cleanup command deletes orphaned images."""
        # 1. Create orphan image and backdate it
        img = create_image_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")
        image_id = response.data["id"]

        uploaded_img = UploadedImage.objects.get(id=image_id)
        uploaded_img.uploaded_at = timezone.now() - timedelta(hours=48)
        uploaded_img.save()

        # 2. Run cleanup
        out = StringIO()
        call_command("cleanup_orphans", stdout=out)

        # 3. Verify deleted
        self.assertFalse(UploadedImage.objects.filter(id=image_id).exists())

    def test_cleanup_keeps_used_images(self):
        """Test that cleanup command keeps images that are referenced."""
        # 1. Create used image
        img = create_image_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")
        image_id = response.data["id"]
        uploaded_img = UploadedImage.objects.get(id=image_id)
        uploaded_img.uploaded_at = timezone.now() - timedelta(hours=48)
        uploaded_img.save()

        # Link it to a question
        quiz = Quiz.objects.create(title="Q", maintainer=self.user)
        Question.objects.create(quiz=quiz, order=1, text="Q", image_upload=uploaded_img)

        # 2. Run cleanup
        call_command("cleanup_orphans", stdout=StringIO())

        # 3. Verify it still exists
        self.assertTrue(UploadedImage.objects.filter(id=image_id).exists())

    def test_cleanup_dry_run(self):
        """Test that cleanup --dry-run doesn't delete anything."""
        # Create orphan
        img = create_image_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")
        image_id = response.data["id"]

        uploaded_img = UploadedImage.objects.get(id=image_id)
        uploaded_img.uploaded_at = timezone.now() - timedelta(hours=48)
        uploaded_img.save()

        # Run with --dry-run
        out = StringIO()
        call_command("cleanup_orphans", "--dry-run", stdout=out)

        # Should still exist
        self.assertTrue(UploadedImage.objects.filter(id=image_id).exists())

    def test_image_upload_priority_over_url(self):
        """Test that image_upload takes priority over image_url in the property."""
        img = create_image_file()
        response = self.client.post(self.upload_url, {"image": img}, format="multipart")
        upload_obj = UploadedImage.objects.get(id=response.data["id"])

        quiz = Quiz.objects.create(title="Test", maintainer=self.user)
        question = Question.objects.create(
            quiz=quiz,
            order=1,
            text="Test",
            image_url="https://external.com/old.jpg",  # External URL
            image_upload=upload_obj,  # Also has upload
        )

        # Upload should take priority
        self.assertIn(upload_obj.image.url, question.image)
        self.assertNotIn("external.com", question.image)
