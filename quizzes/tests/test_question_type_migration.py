import json
import zlib

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from users.models import User


class QuestionTypeMigrationTestCase(TransactionTestCase):
    previous = [("quizzes", "0034_quiz_version")]
    current = [("quizzes", "0035_question_type_enum")]

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def test_forward_reverse_and_forward(self):
        user = User.objects.create(email="migration@example.com", student_number="migration")
        old = self.migrate(self.previous)
        try:
            Quiz = old.get_model("quizzes", "Quiz")
            Question = old.get_model("quizzes", "Question")
            Answer = old.get_model("quizzes", "Answer")
            Version = old.get_model("quizzes", "QuizVersion")
            quiz = Quiz.objects.create(title="Migration", creator_id=user.id, folder_id=user.root_folder_id)
            single = Question.objects.create(quiz=quiz, order=1, question_type=0)
            multiple = Question.objects.create(quiz=quiz, order=2, question_type=0, multiple=True)
            opened = Question.objects.create(quiz=quiz, order=3, question_type=1, multiple=True)
            true_false = [
                Question.objects.create(quiz=quiz, order=i + 4, question_type=2, tf_answer=value)
                for i, value in enumerate((True, False, None))
            ]
            labelled = Question.objects.create(quiz=quiz, order=7, question_type=2, tf_answer=True)
            Answer.objects.create(question=labelled, order=1, text="Tak!", is_correct=True)
            Answer.objects.create(question=labelled, order=2, text="Nie!", is_correct=False)
            version = Version.objects.create(
                quiz=quiz,
                version=1,
                source="create",
                title="Migration",
                snapshot=zlib.compress(
                    json.dumps(
                        {
                            "questions": [
                                {
                                    "question_type": 2,
                                    "multiple": False,
                                    "is_flashcard": False,
                                    "tf_answer": False,
                                    "answers": [],
                                }
                            ]
                        }
                    ).encode()
                ),
            )

            new = self.migrate(self.current)
            Question = new.get_model("quizzes", "Question")
            Version = new.get_model("quizzes", "QuizVersion")
            self.assertEqual(Question.objects.get(pk=single.pk).type, "single_choice")
            self.assertEqual(Question.objects.get(pk=multiple.pk).type, "multiple_choice")
            self.assertEqual(Question.objects.get(pk=opened.pk).type, "open")
            for old_question, expected in zip(true_false, (True, False, True)):
                question = Question.objects.get(pk=old_question.pk)
                self.assertEqual(question.type, "true_false")
                self.assertFalse(question.shuffle_answers)
                self.assertEqual(
                    list(question.answers.values_list("text", "is_correct")),
                    [
                        ("Prawda", expected),
                        ("Fałsz", not expected),
                    ],
                )
            self.assertEqual(
                list(Question.objects.get(pk=labelled.pk).answers.values_list("text", flat=True)),
                [
                    "Tak!",
                    "Nie!",
                ],
            )
            snapshot = json.loads(zlib.decompress(bytes(Version.objects.get(pk=version.pk).snapshot)))
            saved_question = snapshot["questions"][0]
            self.assertEqual(saved_question["type"], "true_false")
            self.assertFalse(saved_question["shuffle_answers"])
            self.assertEqual(saved_question["open_matching"], "exact")
            self.assertNotIn("multiple", saved_question)
            self.assertFalse(saved_question["answers"][0]["is_correct"])

            old = self.migrate(self.previous)
            Question = old.get_model("quizzes", "Question")
            self.assertTrue(Question.objects.get(pk=multiple.pk).multiple)
            self.assertEqual(Question.objects.get(pk=opened.pk).question_type, 1)
            for old_question, expected in zip(true_false, (True, False, True)):
                question = Question.objects.get(pk=old_question.pk)
                self.assertEqual(question.question_type, 2)
                self.assertEqual(question.tf_answer, expected)
            new = self.migrate(self.current)
            self.assertEqual(new.get_model("quizzes", "Question").objects.count(), 7)
            self.assertEqual(new.get_model("quizzes", "Answer").objects.count(), 8)
        finally:
            self.migrate(self.current)
