from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Answer, Question, Quiz, SharedQuiz
from users.models import StudyGroup, User


class CopyQuizTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="user@test.com", first_name="User", last_name="Test", student_number="123456"
        )
        self.owner = User.objects.create(
            email="owner@test.com", first_name="Owner", last_name="Test", student_number="654321"
        )
        self.client.force_authenticate(user=self.user)

        self.quiz = Quiz.objects.create(title="Original Quiz", maintainer=self.owner, visibility=1)
        self.question = Question.objects.create(quiz=self.quiz, order=1, text="Q1")
        self.answer = Answer.objects.create(question=self.question, order=1, text="A1", is_correct=True)

    def test_copy_shared_directly(self):
        SharedQuiz.objects.create(quiz=self.quiz, user=self.user)
        url = reverse("quiz-copy", kwargs={"pk": self.quiz.id})

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Check new quiz exists
        # Original quiz ID is self.quiz.id. We expect a new one.
        new_quiz = Quiz.objects.exclude(id=self.quiz.id).first()
        self.assertIsNotNone(new_quiz)
        self.assertEqual(new_quiz.maintainer, self.user)
        self.assertEqual(new_quiz.title, "Original Quiz - kopia")
        self.assertEqual(new_quiz.questions.count(), 1)
        new_question = new_quiz.questions.first()
        self.assertEqual(new_question.text, "Q1")
        self.assertEqual(new_question.answers.count(), 1)
        self.assertEqual(new_question.answers.first().text, "A1")
        self.assertTrue(new_question.answers.first().is_correct)

    def test_copy_shared_via_group(self):
        group = StudyGroup.objects.create(id="testgroup", name="Test Group")
        group.members.add(self.user)
        # Create shared quiz link so the user can see it
        SharedQuiz.objects.create(quiz=self.quiz, study_group=group)

        url = reverse("quiz-copy", kwargs={"pk": self.quiz.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        new_quiz = Quiz.objects.exclude(id=self.quiz.id).first()
        self.assertIsNotNone(new_quiz)
        self.assertEqual(new_quiz.maintainer, self.user)

    def test_forbidden_if_not_shared(self):
        # Create a quiz that is NOT shared with the current user at all
        # And ensure it's private
        self.quiz.visibility = 0  # Private
        self.quiz.save()

        url = reverse("quiz-copy", kwargs={"pk": self.quiz.id})
        response = self.client.post(url)
        # Returns 404 because get_object() filters queryset
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_copy_own_quiz(self):
        # User owns a quiz
        my_quiz = Quiz.objects.create(title="My Quiz", maintainer=self.user)
        Question.objects.create(quiz=my_quiz, order=1, text="Q1")

        url = reverse("quiz-copy", kwargs={"pk": my_quiz.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        new_quiz = Quiz.objects.exclude(id=my_quiz.id).exclude(id=self.quiz.id).first()
        self.assertIsNotNone(new_quiz)
        self.assertEqual(new_quiz.maintainer, self.user)
        self.assertEqual(new_quiz.title, "My Quiz - kopia")

    def test_throttling(self):
        throttle_user = User.objects.create(
            email="throttle@test.com", first_name="T", last_name="U", student_number="999"
        )
        self.client.force_authenticate(user=throttle_user)

        my_quiz = Quiz.objects.create(title="Throttle Quiz", maintainer=throttle_user)
        url = reverse("quiz-copy", kwargs={"pk": my_quiz.id})

        for _ in range(5):
            response = self.client.post(url)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
