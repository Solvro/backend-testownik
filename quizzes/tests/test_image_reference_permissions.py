"""Upload references must follow readable quiz and uploader authorization."""

from django.test import TestCase
from rest_framework.test import APIClient

from quizzes.models import Answer, Question, Quiz
from uploads.models import UploadedImage
from users.models import User


class ImageReferencePermissionsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="reference-owner@example.invalid")
        self.other = User.objects.create_user(email="reference-other@example.invalid")
        self.quiz = Quiz.objects.create(
            title="Own private quiz", creator=self.owner, folder=self.owner.root_folder, visibility=0
        )
        self.private_quiz = Quiz.objects.create(
            title="Other private quiz", creator=self.other, folder=self.other.root_folder, visibility=0
        )
        self.image = UploadedImage.objects.create(
            image="images/disposable-reference.png",
            original_filename="disposable-reference.png",
            content_type="image/png",
            file_size=1,
            uploaded_by=self.other,
        )
        Question.objects.create(quiz=self.private_quiz, text="Private question", order=0, image_upload=self.image)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def payload(self, target):
        question = {
            "quiz": str(self.quiz.pk),
            "text": "Own question",
            "order": 0,
            "answers": [{"text": "Own answer", "order": 0, "is_correct": True}],
        }
        if target == "question":
            question["image_upload"] = str(self.image.pk)
        else:
            question["answers"][0]["image_upload"] = str(self.image.pk)
        return question

    def test_private_foreign_question_image_cannot_be_attached_by_uuid(self):
        self.assertEqual(self.client.get(f"/api/quizzes/{self.private_quiz.pk}/").status_code, 403)
        response = self.client.post("/api/questions/", self.payload("question"), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Question.objects.filter(quiz=self.quiz).exists())

    def test_private_foreign_answer_image_cannot_be_attached_by_uuid(self):
        response = self.client.post("/api/questions/", self.payload("answer"), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Answer.objects.filter(question__quiz=self.quiz).exists())

    def own_image(self):
        return UploadedImage.objects.create(
            image="images/disposable-own.png",
            original_filename="own.png",
            content_type="image/png",
            file_size=1,
            uploaded_by=self.owner,
        )

    def test_nested_create_rejects_foreign_uploads_without_partial_quiz(self):
        for target in ("question", "answer"):
            with self.subTest(target=target):
                question = self.payload(target)
                question.pop("quiz")
                before = Quiz.objects.count()
                response = self.client.post(
                    "/api/quizzes/", {"title": "Rejected", "questions": [question]}, format="json"
                )
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(Quiz.objects.count(), before)

    def test_new_quiz_cannot_borrow_image_permission_from_unknown_quiz_key(self):
        from quizzes.models import SharedQuiz

        self.private_quiz.visibility = 1
        self.private_quiz.save(update_fields=["visibility"])
        SharedQuiz.objects.create(quiz=self.private_quiz, user=self.owner, allow_edit=True)
        self.assertTrue(self.private_quiz.can_edit(self.owner))
        question = self.payload("question")
        question.pop("quiz")
        before = Quiz.objects.count()
        response = self.client.post(
            "/api/quizzes/",
            {"title": "Rejected cross-quiz reference", "quiz": str(self.private_quiz.pk), "questions": [question]},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Quiz.objects.count(), before)

    def test_nested_question_cannot_override_bulk_or_update_target(self):
        from quizzes.models import SharedQuiz

        self.private_quiz.visibility = 1
        self.private_quiz.save(update_fields=["visibility"])
        SharedQuiz.objects.create(quiz=self.private_quiz, user=self.owner, allow_edit=True)
        self.assertTrue(self.private_quiz.can_edit(self.owner))
        question = self.payload("question")
        question["quiz"] = str(self.private_quiz.pk)
        response = self.client.post(
            "/api/questions/bulk-create/", {"quiz": str(self.quiz.pk), "questions": [question]}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        existing = Question.objects.create(quiz=self.quiz, text="Keep", order=0)
        response = self.client.patch(f"/api/questions/{existing.pk}/", question, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        existing.refresh_from_db()
        self.assertEqual(existing.text, "Keep")
        self.assertIsNone(existing.image_upload_id)

    def test_nested_create_and_new_question_patch_use_the_root_quiz_parent(self):
        question = self.payload("question")
        question["image_upload"] = str(self.own_image().pk)
        created = self.client.post("/api/quizzes/", {"title": "Nested parent", "questions": [question]}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(str(created.data["questions"][0]["quiz"]), str(created.data["id"]))
        self.assertFalse(Question.objects.filter(quiz=self.quiz).exists())
        question["quiz"] = str(created.data["id"])
        updated = self.client.patch(f"/api/quizzes/{self.quiz.pk}/", {"questions": [question]}, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(str(updated.data["questions"][0]["quiz"]), str(self.quiz.pk))
        self.assertEqual(Question.objects.filter(quiz_id=created.data["id"]).count(), 1)

    def test_unknown_questions_key_does_not_hide_the_actual_question_upload(self):
        question = self.payload("question")
        own = self.own_image()
        question["image_upload"] = str(own.pk)
        question["questions"] = [{"image_upload": str(self.image.pk)}]
        response = self.client.post("/api/questions/", question, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["image_upload"], own.pk)

    def test_nested_patch_rejects_foreign_upload_without_changing_version_or_title(self):
        question = self.payload("answer")
        question.pop("quiz")
        response = self.client.patch(
            f"/api/quizzes/{self.quiz.pk}/", {"title": "Must not change", "questions": [question]}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.title, "Own private quiz")
        self.assertEqual(self.quiz.version, 1)

    def test_question_update_rejects_foreign_reference_without_mutation(self):
        question = Question.objects.create(quiz=self.quiz, text="Keep", order=0)
        response = self.client.patch(
            f"/api/questions/{question.pk}/", {"text": "Lose", "image_upload": str(self.image.pk)}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        question.refresh_from_db()
        self.assertEqual(question.text, "Keep")
        self.assertIsNone(question.image_upload_id)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.version, 1)

    def test_bulk_rejection_is_atomic_even_after_a_valid_own_upload(self):
        good = self.payload("question")
        good["image_upload"] = str(self.own_image().pk)
        bad = self.payload("answer")
        for question in (good, bad):
            question.pop("quiz")
        response = self.client.post(
            "/api/questions/bulk-create/", {"quiz": str(self.quiz.pk), "questions": [good, bad]}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Question.objects.filter(quiz=self.quiz).exists())

    def test_own_upload_is_accepted_on_question_answer_and_bulk_paths(self):
        image = self.own_image()
        for target in ("question", "answer"):
            question = self.payload(target)
            item = question if target == "question" else question["answers"][0]
            item["image_upload"] = str(image.pk)
            response = self.client.post("/api/questions/", question, format="json")
            self.assertEqual(response.status_code, 201, response.data)
        question.pop("quiz")
        response = self.client.post(
            "/api/questions/bulk-create/", {"quiz": str(self.quiz.pk), "questions": [question]}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_collaborator_can_reuse_existing_quiz_image_but_not_an_unattached_foreign_upload(self):
        from quizzes.models import SharedQuiz

        self.private_quiz.visibility = 1
        self.private_quiz.save(update_fields=["visibility"])
        SharedQuiz.objects.create(quiz=self.private_quiz, user=self.owner, allow_edit=True)
        self.assertTrue(self.private_quiz.can_edit(self.owner))
        question = self.payload("question")
        question["quiz"] = str(self.private_quiz.pk)
        response = self.client.post("/api/questions/", question, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        unrelated = UploadedImage.objects.create(
            image="images/unattached.png",
            original_filename="unattached.png",
            content_type="image/png",
            file_size=1,
            uploaded_by=self.other,
        )
        question["image_upload"] = str(unrelated.pk)
        response = self.client.post("/api/questions/", question, format="json")
        self.assertEqual(response.status_code, 400, response.data)

    def test_authorized_copy_retains_editable_image_references(self):
        from quizzes.models import SharedQuiz

        self.private_quiz.visibility = 1
        self.private_quiz.save(update_fields=["visibility"])
        SharedQuiz.objects.create(quiz=self.private_quiz, user=self.owner)
        self.assertEqual(self.client.get(f"/api/quizzes/{self.private_quiz.pk}/").status_code, 200)
        copied = self.client.post(f"/api/quizzes/{self.private_quiz.pk}/copy/", format="json")
        self.assertEqual(copied.status_code, 201, copied.data)
        copy_id = copied.data["id"]
        question = copied.data["questions"][0]
        response = self.client.patch(f"/api/quizzes/{copy_id}/", {"questions": [question]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["questions"][0]["image_upload"], self.image.pk)
        # Removing uploader attribution does not invalidate the existing copy.
        self.image.uploaded_by = None
        self.image.save(update_fields=["uploaded_by"])
        response = self.client.patch(f"/api/quizzes/{copy_id}/", {"questions": [question]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        rejected = self.client.post("/api/questions/", self.payload("question"), format="json")
        self.assertEqual(rejected.status_code, 400, rejected.data)

    def test_guest_upgrade_preserves_uploaded_but_not_yet_attached_images(self):
        from users.models import AccountType
        from users.services import migrate_guest_to_user

        guest = User.objects.create_user(email="image-guest@example.invalid", account_type=AccountType.GUEST)
        upload = self.own_image()
        upload.uploaded_by = guest
        upload.save(update_fields=["uploaded_by"])
        self.assertTrue(migrate_guest_to_user(str(guest.pk), self.owner))
        upload.refresh_from_db()
        self.assertEqual(upload.uploaded_by_id, self.owner.pk)
        question = self.payload("answer")
        question["answers"][0]["image_upload"] = str(upload.pk)
        response = self.client.post("/api/questions/", question, format="json")
        self.assertEqual(response.status_code, 201, response.data)

    def test_invalid_upload_uuid_is_a_validation_error(self):
        question = self.payload("question")
        question["image_upload"] = "invalid-uuid"
        response = self.client.post("/api/questions/", question, format="json")
        self.assertEqual(response.status_code, 400, response.data)

    def test_bulk_upload_resolution_is_batched_for_many_unique_images(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        images = UploadedImage.objects.bulk_create(
            [
                UploadedImage(
                    image=f"images/{index}.png",
                    original_filename=f"{index}.png",
                    content_type="image/png",
                    file_size=1,
                    uploaded_by=self.owner,
                )
                for index in range(200)
            ]
        )
        questions = []
        for index, image in enumerate(images):
            question = self.payload("question")
            question.pop("quiz")
            question["order"] = index
            question["image_upload"] = str(image.pk)
            questions.append(question)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(
                "/api/questions/bulk-create/", {"quiz": str(self.quiz.pk), "questions": questions}, format="json"
            )
        self.assertEqual(response.status_code, 201, response.data)
        lookups = [
            q["sql"] for q in queries if q["sql"].startswith("SELECT") and 'FROM "uploads_uploadedimage"' in q["sql"]
        ]
        self.assertLessEqual(len(lookups), 2, lookups)

    def test_quiz_patch_does_not_fetch_each_existing_question_and_answer_image(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        image = self.own_image()
        for index in range(20):
            question = Question.objects.create(
                quiz=self.quiz, text=f"Question {index}", order=index, image_upload=image
            )
            Answer.objects.create(question=question, text="Answer", order=0, is_correct=True, image_upload=image)
        questions = self.client.get(f"/api/quizzes/{self.quiz.pk}/").data["questions"]
        with CaptureQueriesContext(connection) as queries:
            response = self.client.patch(f"/api/quizzes/{self.quiz.pk}/", {"questions": questions}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["questions"]), 20)
        self.assertTrue(all(question["image_upload"] == image.pk for question in response.data["questions"]))
        lookups = [
            query
            for query in queries
            if query["sql"].startswith("SELECT") and 'FROM "uploads_uploadedimage"' in query["sql"]
        ]
        self.assertLessEqual(
            len(lookups), 2, f"Saving 20 unchanged image questions fetched upload rows {len(lookups)} times"
        )

    def test_quiz_patch_can_replace_and_clear_question_and_answer_images(self):
        first, replacement = self.own_image(), self.own_image()
        question = Question.objects.create(quiz=self.quiz, text="Keep", order=0, image_upload=first)
        answer = Answer.objects.create(
            question=question, text="Keep answer", order=0, is_correct=True, image_upload=first
        )
        questions = self.client.get(f"/api/quizzes/{self.quiz.pk}/").data["questions"]
        for image_id in (str(replacement.pk), None):
            with self.subTest(image_id=image_id):
                questions[0]["image_upload"] = image_id
                questions[0]["answers"][0]["image_upload"] = image_id
                response = self.client.patch(f"/api/quizzes/{self.quiz.pk}/", {"questions": questions}, format="json")
                self.assertEqual(response.status_code, 200, response.data)
                question.refresh_from_db()
                answer.refresh_from_db()
                self.assertEqual(str(question.image_upload_id) if question.image_upload_id else None, image_id)
                self.assertEqual(str(answer.image_upload_id) if answer.image_upload_id else None, image_id)
                self.assertEqual(question.text, "Keep")
                self.assertEqual(answer.text, "Keep answer")
