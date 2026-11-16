"""Sharing updates must never transfer access to an unauthorized quiz."""

from django.test import TestCase
from rest_framework.test import APIClient

from quizzes.models import Quiz, SharedQuiz
from users.models import AccountType, StudyGroup, User


class SharingTargetPermissionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="sharing-owner@example.invalid", account_type=AccountType.STUDENT)
        self.foreign_owner = User.objects.create_user(
            email="sharing-foreign@example.invalid", account_type=AccountType.STUDENT
        )
        self.recipient = User.objects.create_user(email="sharing-recipient@example.invalid")
        self.quiz = Quiz.objects.create(title="Owned fixture", creator=self.owner, folder=self.owner.root_folder)
        self.foreign_quiz = Quiz.objects.create(
            title="Private foreign fixture",
            creator=self.foreign_owner,
            folder=self.foreign_owner.root_folder,
            visibility=0,
        )
        self.grant = SharedQuiz.objects.create(quiz=self.quiz, user=self.recipient)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = f"/api/shared-quizzes/{self.grant.id}/"

    def test_patch_cannot_repoint_owned_grant_to_foreign_private_quiz(self):
        response = self.client.patch(
            self.url,
            {"quiz_id": str(self.foreign_quiz.id), "user_id": str(self.owner.id), "allow_edit": True},
            format="json",
        )
        self.grant.refresh_from_db()
        self.assertIn(
            response.status_code,
            (400, 403),
            f"quiz_reassigned={self.grant.quiz_id == self.foreign_quiz.id}; "
            f"foreign_edit_access={self.foreign_quiz.can_edit(self.owner)}",
        )
        self.assertEqual(self.grant.quiz_id, self.quiz.id)
        self.assertEqual(self.grant.user_id, self.recipient.id)
        self.assertFalse(self.grant.allow_edit)
        self.assertFalse(self.foreign_quiz.can_edit(self.owner))

    def test_role_update_accepts_the_unchanged_quiz_identifier(self):
        response = self.client.patch(self.url, {"quiz_id": str(self.quiz.id), "allow_edit": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.quiz_id, self.quiz.id)
        self.assertEqual(self.grant.user_id, self.recipient.id)
        self.assertTrue(self.grant.allow_edit)

    def test_put_cannot_repoint_owned_grant_to_foreign_private_quiz(self):
        response = self.client.put(
            self.url,
            {"quiz_id": str(self.foreign_quiz.id), "user_id": str(self.owner.id), "allow_edit": True},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("quiz_id", response.data)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.quiz_id, self.quiz.id)
        self.assertEqual(self.grant.user_id, self.recipient.id)
        self.assertFalse(self.foreign_quiz.can_edit(self.owner))

    def test_role_only_patch_still_works(self):
        response = self.client.patch(self.url, {"allow_edit": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.grant.refresh_from_db()
        self.assertTrue(self.grant.allow_edit)
        self.assertEqual(self.grant.quiz_id, self.quiz.id)

    def test_full_update_with_the_same_quiz_still_works(self):
        response = self.client.put(
            self.url,
            {"quiz_id": str(self.quiz.id), "user_id": str(self.recipient.id), "allow_edit": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.grant.refresh_from_db()
        self.assertTrue(self.grant.allow_edit)
        self.assertEqual(self.grant.quiz_id, self.quiz.id)
        self.assertEqual(self.grant.user_id, self.recipient.id)

    def test_post_still_creates_an_owned_quiz_grant(self):
        response = self.client.post(
            "/api/shared-quizzes/",
            {"quiz_id": str(self.quiz.id), "user_id": str(self.owner.id), "allow_edit": False},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(SharedQuiz.objects.filter(quiz=self.quiz, user=self.owner).exists())

    def test_post_cannot_grant_a_foreign_private_quiz(self):
        response = self.client.post(
            "/api/shared-quizzes/",
            {"quiz_id": str(self.foreign_quiz.id), "user_id": str(self.owner.id), "allow_edit": True},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SharedQuiz.objects.filter(quiz=self.foreign_quiz, user=self.owner).exists())

    def test_delete_an_owned_quiz_grant_still_works(self):
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(SharedQuiz.objects.filter(pk=self.grant.id).exists())

    def test_quiz_only_patch_cannot_repoint_an_edit_collaborators_grant(self):
        self.quiz.visibility = 1
        self.quiz.save(update_fields=["visibility"])
        self.grant.allow_edit = True
        self.grant.save(update_fields=["allow_edit"])
        self.client.force_authenticate(self.recipient)
        response = self.client.patch(self.url, {"quiz_id": str(self.foreign_quiz.id)}, format="json")
        self.assertEqual(response.status_code, 400)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.quiz_id, self.quiz.id)
        self.assertFalse(self.foreign_quiz.can_edit(self.recipient))

    def test_a_share_cannot_be_moved_between_two_owned_quizzes(self):
        second = Quiz.objects.create(title="Second owned fixture", creator=self.owner, folder=self.owner.root_folder)
        response = self.client.patch(self.url, {"quiz_id": str(second.id)}, format="json")
        self.assertEqual(response.status_code, 400)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.quiz_id, self.quiz.id)

    def test_read_only_recipient_cannot_promote_their_grant(self):
        self.quiz.visibility = 1
        self.quiz.save(update_fields=["visibility"])
        self.client.force_authenticate(self.recipient)
        response = self.client.patch(self.url, {"allow_edit": True}, format="json")
        self.assertEqual(response.status_code, 403)
        self.grant.refresh_from_db()
        self.assertFalse(self.grant.allow_edit)

    def test_edit_recipient_can_downgrade_their_grant_on_the_same_quiz(self):
        self.quiz.visibility = 1
        self.quiz.save(update_fields=["visibility"])
        self.grant.allow_edit = True
        self.grant.save(update_fields=["allow_edit"])
        self.client.force_authenticate(self.recipient)
        response = self.client.patch(self.url, {"quiz_id": str(self.quiz.id), "allow_edit": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.grant.refresh_from_db()
        self.assertFalse(self.grant.allow_edit)

    def test_group_role_update_stays_on_its_quiz(self):
        group = StudyGroup.objects.create(id="sharing-fixture-group", name="Fixture group")
        grant = SharedQuiz.objects.create(quiz=self.quiz, study_group=group)
        response = self.client.patch(f"/api/shared-quizzes/{grant.id}/", {"allow_edit": True}, format="json")
        self.assertEqual(response.status_code, 200)
        grant.refresh_from_db()
        self.assertTrue(grant.allow_edit)
        self.assertEqual(grant.quiz_id, self.quiz.id)
        self.assertEqual(grant.study_group_id, group.id)

    def test_missing_quiz_identifier_is_rejected_without_altering_grant(self):
        import uuid

        response = self.client.patch(self.url, {"quiz_id": str(uuid.uuid4())}, format="json")
        self.assertEqual(response.status_code, 400)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.quiz_id, self.quiz.id)
