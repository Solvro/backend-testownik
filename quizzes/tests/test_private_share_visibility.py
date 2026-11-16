"""Private visibility must suspend saved direct and group invitations."""

from django.test import TestCase
from rest_framework.test import APIClient

from quizzes.models import Quiz, QuizShortcut, SharedFolder, SharedQuiz
from users.models import AccountType, StudyGroup, User


class PrivateShareVisibilityTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="visibility-owner@example.invalid", account_type=AccountType.STUDENT
        )
        self.recipient = User.objects.create_user(
            email="visibility-recipient@example.invalid", account_type=AccountType.STUDENT
        )
        self.quiz = Quiz.objects.create(
            title="Private fixture", creator=self.owner, folder=self.owner.root_folder, visibility=0
        )
        self.client = APIClient()
        self.client.force_authenticate(self.recipient)
        self.url = f"/api/quizzes/{self.quiz.pk}/"

    def grant(self, mode):
        if mode == "user":
            return SharedQuiz.objects.create(quiz=self.quiz, user=self.recipient, allow_edit=True)
        group = StudyGroup.objects.create(id="visibility-fixture-group", name="Visibility fixture")
        group.members.add(self.recipient)
        return SharedQuiz.objects.create(quiz=self.quiz, study_group=group, allow_edit=True)

    def test_private_visibility_blocks_existing_invitation_read(self):
        for mode in ("user", "group"):
            with self.subTest(mode=mode):
                grant = self.grant(mode)
                try:
                    response = self.client.get(self.url)
                    self.assertEqual(response.status_code, 403)
                    self.assertTrue(SharedQuiz.objects.filter(pk=grant.pk).exists())
                finally:
                    grant.delete()

    def test_private_visibility_blocks_existing_invitation_edit(self):
        for mode in ("user", "group"):
            with self.subTest(mode=mode):
                grant = self.grant(mode)
                try:
                    self.assertFalse(self.quiz.can_edit(self.recipient))
                    response = self.client.patch(self.url, {"title": "Unauthorized replacement"}, format="json")
                    self.quiz.refresh_from_db()
                    self.assertEqual(response.status_code, 403, f"title_changed={self.quiz.title != 'Private fixture'}")
                    self.assertEqual(self.quiz.title, "Private fixture")
                finally:
                    grant.delete()
                    self.quiz.title = "Private fixture"
                    self.quiz.save(update_fields=["title"])

    def test_invited_visibility_allows_existing_invitation_read_and_edit(self):
        self.quiz.visibility = 1
        self.quiz.save(update_fields=["visibility"])
        self.grant("user")
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(
            self.client.patch(self.url, {"title": "Authorized replacement"}, format="json").status_code, 200
        )
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.title, "Authorized replacement")

    def test_owner_keeps_private_read_and_edit(self):
        self.client.force_authenticate(self.owner)
        self.assertTrue(self.quiz.can_edit(self.owner))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.patch(self.url, {"title": "Owner replacement"}, format="json").status_code, 200)

    def test_private_then_shared_reactivates_the_same_direct_and_group_grants(self):
        for mode in ("user", "group"):
            with self.subTest(mode=mode):
                grant = self.grant(mode)
                try:
                    self.client.force_authenticate(self.owner)
                    self.assertEqual(self.client.patch(self.url, {"visibility": 1}, format="json").status_code, 200)
                    self.client.force_authenticate(self.recipient)
                    self.assertEqual(self.client.get(self.url).status_code, 200)
                    self.client.force_authenticate(self.owner)
                    self.assertEqual(self.client.patch(self.url, {"visibility": 0}, format="json").status_code, 200)
                    self.client.force_authenticate(self.recipient)
                    self.assertEqual(self.client.get(self.url).status_code, 403)
                    grant.refresh_from_db()
                    self.assertTrue(grant.allow_edit)
                    self.assertEqual(grant.quiz_id, self.quiz.id)
                    self.client.force_authenticate(self.owner)
                    self.assertEqual(self.client.patch(self.url, {"visibility": 1}, format="json").status_code, 200)
                    self.client.force_authenticate(self.recipient)
                    self.assertEqual(self.client.get(self.url).status_code, 200)
                    self.assertEqual(
                        self.client.patch(self.url, {"title": "Restored collaborator"}, format="json").status_code, 200
                    )
                    self.assertTrue(SharedQuiz.objects.filter(pk=grant.pk, allow_edit=True).exists())
                finally:
                    grant.delete()

    def test_existing_folder_edit_capability_is_preserved(self):
        SharedFolder.objects.create(folder=self.owner.root_folder, user=self.recipient, allow_edit=True)
        self.assertEqual(self.quiz.visibility, 0)
        self.assertTrue(self.quiz.can_edit(self.recipient))

    def test_private_invitation_cannot_copy_quiz(self):
        self.grant("user")
        before = Quiz.objects.count()
        self.assertEqual(self.client.post(f"{self.url}copy/", format="json").status_code, 403)
        self.assertEqual(Quiz.objects.count(), before)

    def test_private_invitation_cannot_grant_access_to_another_person(self):
        self.grant("user")
        response = self.client.post(
            "/api/shared-quizzes/",
            {"quiz_id": str(self.quiz.id), "user_id": str(self.owner.id), "allow_edit": True},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(SharedQuiz.objects.filter(quiz=self.quiz).count(), 1)

    def test_private_invitation_hides_saved_shortcut_without_deleting_it(self):
        self.grant("user")
        shortcut = QuizShortcut.objects.create(quiz=self.quiz, folder=self.recipient.root_folder, owner=self.recipient)
        response = self.client.get("/api/library/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(str(self.quiz.id), {str(item["id"]) for item in response.data["items"]})
        self.assertTrue(QuizShortcut.objects.filter(pk=shortcut.pk).exists())
