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

    def test_copy_complex_structure(self):
        # Create a quiz with multiple questions and answers
        complex_quiz = Quiz.objects.create(title="Complex Quiz", maintainer=self.owner, visibility=2)

        # Q1: 2 answers
        q1 = Question.objects.create(quiz=complex_quiz, order=1, text="Q1")
        Answer.objects.create(question=q1, order=1, text="A1-1", is_correct=True)
        Answer.objects.create(question=q1, order=2, text="A1-2", is_correct=False)

        # Q2: 3 answers
        q2 = Question.objects.create(quiz=complex_quiz, order=2, text="Q2")
        Answer.objects.create(question=q2, order=1, text="A2-1", is_correct=False)
        Answer.objects.create(question=q2, order=2, text="A2-2", is_correct=True)
        Answer.objects.create(question=q2, order=3, text="A2-3", is_correct=False)

        url = reverse("quiz-copy", kwargs={"pk": complex_quiz.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        new_quiz = Quiz.objects.exclude(id=complex_quiz.id).exclude(id=self.quiz.id).first()
        self.assertIsNotNone(new_quiz)
        self.assertEqual(new_quiz.questions.count(), 2)

        new_q1 = new_quiz.questions.get(order=1)
        self.assertEqual(new_q1.text, "Q1")
        self.assertEqual(new_q1.answers.count(), 2)
        self.assertTrue(new_q1.answers.get(order=1).is_correct)

        new_q2 = new_quiz.questions.get(order=2)
        self.assertEqual(new_q2.text, "Q2")
        self.assertEqual(new_q2.answers.count(), 3)
        self.assertTrue(new_q2.answers.get(order=2).is_correct)

    def test_copy_public_quiz(self):
        # Public quiz (visibility=3) not owned/shared
        # Using visibility=3 to ensure it's fully public
        public_quiz = Quiz.objects.create(title="Public Quiz", maintainer=self.owner, visibility=3)

        url = reverse("quiz-copy", kwargs={"pk": public_quiz.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        new_quiz = Quiz.objects.exclude(id=public_quiz.id).filter(title="Public Quiz - kopia").first()
        self.assertIsNotNone(new_quiz)
        self.assertEqual(new_quiz.maintainer, self.user)
        # Verify visibility is reset to default (2 - Unlisted)
        self.assertEqual(new_quiz.visibility, 2)

    def test_copy_empty_quiz(self):
        empty_quiz = Quiz.objects.create(title="Empty Quiz", maintainer=self.owner, visibility=2)

        url = reverse("quiz-copy", kwargs={"pk": empty_quiz.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        new_quiz = Quiz.objects.exclude(id=empty_quiz.id).filter(title="Empty Quiz - kopia").first()
        self.assertIsNotNone(new_quiz)
        self.assertEqual(new_quiz.questions.count(), 0)
