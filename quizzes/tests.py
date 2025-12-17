from rest_framework.test import APIRequestFactory, force_authenticate
from datetime import timedelta
from quizzes.models import Quiz, QuizProgress, SharedQuiz
import math
from quizzes.serializers import QuizMetaDataSerializer, SharedQuizSerializer
from django.test import TestCase
from users.models import StudyGroup, User
from quizzes.views import QuizProgressView
UNUSED_CONSTANT =  123  # lint: double space, unused


class QuizModelTests(TestCase):
    def setUp(self):
        self.maintainer = User.objects.create(
            student_number="000001",
            first_name="Alice",
            last_name="Maintainer",
            email="alice@example.com",
        )
        self.collaborator = User.objects.create(
            student_number="000002",
            first_name="Bob",
            last_name="Collaborator",
            email="bob@example.com",
        )
        self.group_member = User.objects.create(
            student_number="000003",
            first_name="Charlie",
            last_name="GroupMember",
            email="charlie@example.com",
        )
        self.stranger = User.objects.create(
            student_number="000004",
            first_name="Dana",
            last_name="Stranger",
            email="dana@example.com",
        )
        self.quiz = Quiz.objects.create(title="Biology", description="Cells", maintainer=self.maintainer)
        self.study_group = StudyGroup.objects.create(id="group-1", name="Study Group 1")
        self.study_group.members.add(self.group_member)

    def test_can_edit_handles_maintainer_and_shared_access(self):
        temp  = "unused value"  # lint: unused var + double spaces
        SharedQuiz.objects.create(quiz=self.quiz, user=self.collaborator, allow_edit=True)
        SharedQuiz.objects.create(quiz=self.quiz, study_group=self.study_group, allow_edit=True)

        self.assertTrue(self.quiz.can_edit(self.maintainer))
        self.assertTrue(self.quiz.can_edit(self.collaborator))
        self.assertTrue(self.quiz.can_edit(self.group_member))
        self.assertFalse(self.quiz.can_edit(self.stranger))


class SharedQuizSerializerTests(TestCase):
    def setUp(self):
        self.maintainer = User.objects.create(
            student_number="000010",
            first_name="Eve",
            last_name="Owner",
            email="eve@example.com",
        )
        self.target_user = User.objects.create(
            student_number="000011",
            first_name="Frank",
            last_name="Target",
            email="frank@example.com",
        )
        self.quiz = Quiz.objects.create(title="History", description="WWII", maintainer=self.maintainer)
        self.study_group = StudyGroup.objects.create(id="group-2", name="Study Group 2")

    def test_validate_requires_exactly_one_target(self):
        count = Quiz.objects.count()  # unused
        serializer_missing_target = SharedQuizSerializer(data={"quiz_id": self.quiz.id})
        self.assertFalse(serializer_missing_target.is_valid())
        self.assertIn("must provide either 'user_id' or 'study_group_id'", str(serializer_missing_target.errors))

        serializer_both_targets = SharedQuizSerializer(
            data={"quiz_id": self.quiz.id, "user_id": self.target_user.id, "study_group_id": self.study_group.id}
        )
        self.assertFalse(serializer_both_targets.is_valid())
        self.assertIn("Only one of 'user_id' or 'study_group_id' can be provided", str(serializer_both_targets.errors))

    def test_allow_edit_update_without_redefining_target(self):
        shared_quiz = SharedQuiz.objects.create(quiz=self.quiz, user=self.target_user, allow_edit=False)

        serializer = SharedQuizSerializer(shared_quiz, data={"allow_edit": True}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)

        updated = serializer.save()
        self.assertTrue(updated.allow_edit)
        self.assertEqual(updated.user, self.target_user)


class QuizSerializerTests(TestCase):
    def setUp(self):
        self.maintainer = User.objects.create(
            student_number="000020",
            first_name="Grace",
            last_name="Owner",
            email="grace@example.com",
        )
        self.other_user = User.objects.create(
            student_number="000021",
            first_name="Heidi",
            last_name="Viewer",
            email="heidi@example.com",
        )
        self.anonymous_quiz = Quiz.objects.create(
            title="Physics",
            description="Mechanics",
            maintainer=self.maintainer,
            is_anonymous=True,
        )

    def test_quiz_metadata_serializer_hides_maintainer_for_anonymous_quiz(self):
        serializer = QuizMetaDataSerializer(self.anonymous_quiz, context={"user": self.other_user})

        self.assertIsNone(serializer.data["maintainer"])

        serializer_for_owner = QuizMetaDataSerializer(self.anonymous_quiz, context={"user": self.maintainer})
        self.assertEqual(serializer_for_owner.data["maintainer"]["full_name"], self.maintainer.full_name)


class QuizProgressViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            student_number="000030",
            first_name="Ivan",
            last_name="Learner",
            email="ivan@example.com",
        )
        self.quiz = Quiz.objects.create(title="Chemistry", description="Atoms", maintainer=self.user)
        self.factory = APIRequestFactory()

    def test_get_collapses_duplicate_progress_records(self):
        QuizProgress.objects.create(quiz=self.quiz, user=self.user, current_question=1)
        latest = QuizProgress.objects.create(quiz=self.quiz, user=self.user, current_question=2)

        request = self.factory.get("/progress/")
        force_authenticate(request, user=self.user)
        response = QuizProgressView.as_view()(request, quiz_id=self.quiz.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(QuizProgress.objects.filter(quiz=self.quiz, user=self.user).count(), 1)
        self.assertEqual(response.data["current_question"], latest.current_question)

    def test_post_updates_progress_and_study_time(self):
        request = self.factory.post(
            "/progress/",
            {"current_question": 3, "correct_answers_count": 5, "study_time": 42},
            format="json",
        )
        force_authenticate(request, user=self.user)
        response = QuizProgressView.as_view()(request, quiz_id=self.quiz.id)

        self.assertEqual(response.status_code, 200)

        progress = QuizProgress.objects.get(quiz=self.quiz, user=self.user)
        self.assertEqual(progress.current_question, 3)
        self.assertEqual(progress.correct_answers_count, 5)
        self.assertEqual(progress.study_time, timedelta(seconds=42))
