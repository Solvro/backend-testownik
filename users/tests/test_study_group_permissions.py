"""Only the university synchronization owns shared study-group metadata."""

from django.test import TestCase
from rest_framework.test import APIClient

from quizzes.models import Quiz, SharedFolder, SharedQuiz
from users.models import AccountType, StudyGroup, User


class StudyGroupPermissionTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(email="group-member@example.invalid", account_type=AccountType.STUDENT)
        self.peer = User.objects.create_user(email="group-peer@example.invalid", account_type=AccountType.STUDENT)
        self.owner = User.objects.create_user(email="group-owner@example.invalid", account_type=AccountType.LECTURER)
        self.outsider = User.objects.create_user(email="group-outsider@example.invalid")
        self.group = StudyGroup.objects.create(id="course-permission-fixture", name="University fixture group")
        self.group.members.add(self.member, self.peer)
        self.quiz = Quiz.objects.create(
            title="Group fixture quiz", creator=self.owner, folder=self.owner.root_folder, visibility=1
        )
        self.quiz_grant = SharedQuiz.objects.create(quiz=self.quiz, study_group=self.group)
        self.folder_grant = SharedFolder.objects.create(folder=self.owner.root_folder, study_group=self.group)
        self.client = APIClient()
        self.client.force_authenticate(self.member)
        self.url = f"/api/study-groups/{self.group.id}/"

    def test_member_cannot_delete_global_group_and_other_users_grants(self):
        response = self.client.delete(self.url)
        self.assertIn(
            response.status_code,
            (403, 405),
            f"group_exists={StudyGroup.objects.filter(pk=self.group.pk).exists()}; "
            f"peer_membership_exists={self.peer.study_groups.filter(pk=self.group.pk).exists()}; "
            f"quiz_grant_exists={SharedQuiz.objects.filter(pk=self.quiz_grant.pk).exists()}; "
            f"folder_grant_exists={SharedFolder.objects.filter(pk=self.folder_grant.pk).exists()}",
        )
        self.assertTrue(StudyGroup.objects.filter(pk=self.group.pk).exists())
        self.assertTrue(self.peer.study_groups.filter(pk=self.group.pk).exists())
        self.assertTrue(SharedQuiz.objects.filter(pk=self.quiz_grant.pk).exists())
        self.assertTrue(SharedFolder.objects.filter(pk=self.folder_grant.pk).exists())

    def test_member_cannot_rename_the_group_for_every_member(self):
        response = self.client.patch(self.url, {"name": "Attacker supplied title"}, format="json")
        self.group.refresh_from_db()
        self.assertIn(
            response.status_code, (403, 405), f"stored_name_changed={self.group.name != 'University fixture group'}"
        )
        self.assertEqual(self.group.name, "University fixture group")

    def test_member_can_list_and_retrieve_their_group(self):
        response = self.client.get("/api/study-groups/")
        self.assertEqual(response.status_code, 200)
        entries = response.data.get("results", []) if isinstance(response.data, dict) else response.data
        self.assertEqual([entry["id"] for entry in entries], [self.group.id])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], self.group.id)

    def test_outsider_cannot_read_the_group(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        response = self.client.get("/api/study-groups/")
        self.assertEqual(response.status_code, 200)
        entries = response.data.get("results", []) if isinstance(response.data, dict) else response.data
        self.assertEqual(entries, [])

    def test_member_cannot_create_a_group_through_the_api(self):
        response = self.client.post(
            "/api/study-groups/", {"id": "forged-university-group", "name": "Forged group"}, format="json"
        )
        self.assertEqual(response.status_code, 405)
        self.assertFalse(StudyGroup.objects.filter(pk="forged-university-group").exists())

    def test_member_cannot_replace_a_group_through_the_api(self):
        response = self.client.put(self.url, {"name": "Replaced group"}, format="json")
        self.assertEqual(response.status_code, 405)
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "University fixture group")

    def test_anonymous_cannot_list_or_retrieve_groups(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get("/api/study-groups/").status_code, (401, 403))
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_supported_methods_are_read_only(self):
        response = self.client.options(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response["Allow"].replace(" ", "").split(",")), {"GET", "HEAD", "OPTIONS"})
        self.assertEqual(self.client.head(self.url).status_code, 200)
