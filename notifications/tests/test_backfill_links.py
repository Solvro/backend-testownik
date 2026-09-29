from importlib import import_module

from django.apps import apps
from django.test import TestCase, override_settings

from notifications.models import Notification, NotificationType
from quizzes.models import Quiz, SharedQuiz
from users.models import StudyGroup, User

backfill_links = import_module("notifications.migrations.0006_backfill_quiz_shared_links").backfill_links


def shared(user, title):
    return Notification.objects.create(
        user=user,
        title="Cześć! 👋",
        content=f'Quiz <strong>"{title}"</strong> został Ci udostępniony.',
        notification_type=NotificationType.EMAIL,
    )


@override_settings(FRONTEND_URL="https://testownik.example")
class BackfillQuizSharedLinksTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create(email="owner@test.com", student_number="200000")
        self.member = User.objects.create(email="member@test.com", student_number="200001")
        self.classmate = User.objects.create(email="classmate@test.com", student_number="200002")
        self.group = StudyGroup.objects.create(id="group", name="Group")
        self.group.members.add(self.member, self.classmate)
        # Two quizzes share a title: one via the group, one directly.
        self.group_quiz = Quiz.objects.create(title="Same", creator=self.owner, folder=self.owner.root_folder)
        self.direct_quiz = Quiz.objects.create(title="Same", creator=self.owner, folder=self.owner.root_folder)
        SharedQuiz.objects.create(quiz=self.group_quiz, study_group=self.group)
        SharedQuiz.objects.create(quiz=self.direct_quiz, user=self.member)

    def test_links_group_and_direct_shares_to_their_quiz(self):
        from_group = shared(self.member, "Same")
        shared(self.classmate, "Same")
        backfill_links(apps, None)
        from_group.refresh_from_db()
        self.assertEqual(from_group.link, f"https://testownik.example/quiz/{self.group_quiz.id}")

        Notification.objects.exclude(pk=from_group.pk).delete()
        direct = shared(self.member, "Same")
        backfill_links(apps, None)
        direct.refresh_from_db()
        self.assertEqual(direct.link, f"https://testownik.example/quiz/{self.direct_quiz.id}")

    def test_leaves_unknown_quizzes_without_link(self):
        notification = shared(self.member, "Missing")
        backfill_links(apps, None)
        notification.refresh_from_db()
        self.assertEqual(notification.link, "")
