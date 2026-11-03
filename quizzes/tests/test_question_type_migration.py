import json
import uuid
import zlib
from importlib import import_module
from unittest.mock import patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from users.models import User


class QuestionTypeMigrationTestCase(TransactionTestCase):
    previous = [("quizzes", "0034_quiz_version")]
    expanded = [("quizzes", "0035_question_type_fields")]
    current = [("quizzes", "0037_remove_question_legacy_fields")]

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def old_snapshot(self, quiz):
        # The pre-enum build_snapshot field list deliberately excludes tf_answer.
        fields = (
            "order",
            "text",
            "explanation",
            "multiple",
            "question_type",
            "is_markdown_enabled",
            "is_ai_generated",
            "is_flashcard",
            "image_url",
        )
        return {
            "title": quiz.title,
            "description": "",
            "questions": [
                {
                    "id": str(q.id),
                    **{field: getattr(q, field) for field in fields},
                    "image_upload": None,
                    "answers": [
                        {
                            "id": str(a.id),
                            "order": a.order,
                            "text": a.text,
                            "is_correct": a.is_correct,
                            "image_url": None,
                            "image_upload": None,
                        }
                        for a in q.answers.order_by("order", "id")
                    ],
                }
                for q in quiz.questions.order_by("order", "id")
            ],
        }

    def test_forward_reverse_and_forward(self):
        user = User.objects.create(email="migration@example.com", student_number="migration")
        old = self.migrate(self.previous)
        try:
            Quiz = old.get_model("quizzes", "Quiz")
            Question = old.get_model("quizzes", "Question")
            Answer = old.get_model("quizzes", "Answer")
            Version = old.get_model("quizzes", "QuizVersion")
            quiz = Quiz.objects.create(title="Migration", creator_id=user.id, folder_id=user.root_folder_id)
            single = Question.objects.create(quiz=quiz, order=1, question_type=0, is_flashcard=True)
            multiple = Question.objects.create(quiz=quiz, order=2, question_type=0, multiple=True)
            opened = Question.objects.create(quiz=quiz, order=3, question_type=1, multiple=True)
            tf = [
                Question.objects.create(quiz=quiz, order=i + 4, question_type=2, tf_answer=value)
                for i, value in enumerate((True, False, None, True, False, None, None, None))
            ]
            # Conflicting marks: live tf_answer is authoritative, labels survive.
            for i, text in enumerate(("Tak!", "Nie!")):
                Answer.objects.create(question=tf[3], order=5 + i, text=text, is_correct=i == 1)
            # Extras and blank labels must become two default labels.
            for i in range(3):
                Answer.objects.create(question=tf[4], order=i + 1, text="Extra", is_correct=True)
            for i in range(2):
                Answer.objects.create(question=tf[5], order=i + 1, text="" if i else "Yes", is_correct=i == 1)
                Answer.objects.create(question=tf[6], order=i + 1, text="Label", is_correct=True)
            for i in range(3):
                Answer.objects.create(question=tf[7], order=i + 1, text="Extra", is_correct=i == 2)
            preserved_id = tf[7].answers.get(is_correct=True).pk
            snapshot = self.old_snapshot(quiz)
            self.assertTrue(all("tf_answer" not in q for q in snapshot["questions"]))
            missing = {**snapshot["questions"][4], "id": str(uuid.uuid4()), "answers": []}
            snapshot["questions"].append(missing)
            versions = [
                Version.objects.create(
                    quiz=quiz,
                    version=i + 1,
                    source="create",
                    title="Migration",
                    snapshot=zlib.compress(json.dumps(snapshot).encode()),
                )
                for i in range(3)
            ]

            old_fields = {field.name for field in Question._meta.fields}
            expanded = self.migrate(self.expanded)
            self.assertEqual(
                {field.name for field in expanded.get_model("quizzes", "Question")._meta.fields},
                old_fields | {"type", "open_matching"},
            )
            self.assertEqual(
                expanded.get_model("quizzes", "Question").objects.get(pk=multiple.pk).type, "single_choice"
            )
            self.assertEqual(Version.objects.get(pk=versions[0].pk).snapshot, versions[0].snapshot)
            module = import_module("quizzes.migrations.0036_question_type_data")
            with (
                patch.object(module, "QUESTION_BATCH_SIZE", 2),
                patch.object(module, "VERSION_BATCH_SIZE", 2),
                self.assertLogs(module.logger, level="WARNING") as warnings,
            ):
                new = self.migrate(self.current)
            self.assertTrue(any(str(tf[2].pk) in line for line in warnings.output))
            self.assertTrue(any(missing["id"] in line for line in warnings.output))
            Question = new.get_model("quizzes", "Question")
            Version = new.get_model("quizzes", "QuizVersion")
            self.assertEqual(Question.objects.get(pk=single.pk).type, "single_choice")
            self.assertEqual(
                {field.name for field in Question._meta.fields},
                (old_fields - {"is_flashcard", "multiple", "question_type", "tf_answer"}) | {"type", "open_matching"},
            )
            self.assertEqual(Question.objects.get(pk=multiple.pk).type, "multiple_choice")
            self.assertEqual(Question.objects.get(pk=opened.pk).type, "open")
            expected_first = (True, False, True, True, False, False, True, False)
            for index, (q, first) in enumerate(zip(tf, expected_first)):
                live = Question.objects.get(pk=q.pk)
                self.assertEqual(list(live.answers.values_list("order", "is_correct")), [(1, first), (2, not first)])
                labels = ["Tak!", "Nie!"] if index == 3 else ["Label", "Label"] if index == 6 else ["Prawda", "Fałsz"]
                self.assertEqual(list(live.answers.values_list("text", flat=True)), labels)
            self.assertTrue(Question.objects.get(pk=tf[7].pk).answers.filter(pk=preserved_id, is_correct=True).exists())
            for version in versions:
                saved = json.loads(zlib.decompress(bytes(Version.objects.get(pk=version.pk).snapshot)))
                by_id = {q["id"]: q for q in saved["questions"]}
                # Snapshot answers override the conflicting live tf_answer.
                self.assertFalse(by_id[str(tf[3].pk)]["answers"][0]["is_correct"])
                # Empty snapshot falls back to the live False rather than True.
                self.assertFalse(by_id[str(tf[1].pk)]["answers"][0]["is_correct"])
                self.assertTrue(by_id[missing["id"]]["answers"][0]["is_correct"])
                for q in saved["questions"]:
                    self.assertEqual(
                        set(q),
                        (set(snapshot["questions"][0]) - {"multiple", "question_type", "is_flashcard"})
                        | {"type", "open_matching"},
                    )
                    self.assertNotIn("multiple", q)
                    self.assertNotIn("is_flashcard", q)
                    self.assertNotIn("tf_answer", q)

            old = self.migrate(self.previous)
            Question = old.get_model("quizzes", "Question")
            Version = old.get_model("quizzes", "QuizVersion")
            self.assertTrue(Question.objects.get(pk=multiple.pk).multiple)
            self.assertEqual(Question.objects.get(pk=opened.pk).question_type, 1)
            self.assertFalse(Question.objects.get(pk=single.pk).is_flashcard)
            for q, first in zip(tf, expected_first):
                self.assertEqual(Question.objects.get(pk=q.pk).tf_answer, first)
            reversed_snapshot = json.loads(zlib.decompress(bytes(Version.objects.get(pk=versions[0].pk).snapshot)))
            by_id = {q["id"]: q for q in reversed_snapshot["questions"]}
            self.assertFalse(by_id[str(tf[3].pk)]["tf_answer"])
            self.assertTrue(by_id[str(multiple.pk)]["multiple"])
            self.assertEqual(by_id[str(opened.pk)]["question_type"], 1)
            new = self.migrate(self.current)
            self.assertEqual(new.get_model("quizzes", "Question").objects.count(), 11)
            self.assertEqual(new.get_model("quizzes", "Answer").objects.count(), 16)
        finally:
            self.migrate(self.current)

    def test_interrupted_snapshot_conversion_resumes_in_both_directions(self):
        user = User.objects.create(email="resume@example.com", student_number="resume")
        old = self.migrate(self.previous)
        try:
            Quiz = old.get_model("quizzes", "Quiz")
            Question = old.get_model("quizzes", "Question")
            Answer = old.get_model("quizzes", "Answer")
            Version = old.get_model("quizzes", "QuizVersion")
            quiz = Quiz.objects.create(title="Resume", creator_id=user.id, folder_id=user.root_folder_id)
            multiple = Question.objects.create(quiz=quiz, order=1, question_type=0, multiple=True)
            tf = Question.objects.create(quiz=quiz, order=2, question_type=2, tf_answer=False)
            Answer.objects.create(question=multiple, order=1, text="A", is_correct=True)
            snapshot = zlib.compress(json.dumps(self.old_snapshot(quiz)).encode())
            versions = [
                Version.objects.create(quiz=quiz, version=i + 1, source="create", title="Resume", snapshot=snapshot)
                for i in range(3)
            ]
            module = import_module("quizzes.migrations.0036_question_type_data")
            original = module.batches

            def failing_after_first_version_batch(queryset, size):
                pages = original(queryset, size)
                if queryset.model._meta.model_name != "quizversion":
                    yield from pages
                    return
                yield next(pages)
                raise RuntimeError("interrupted")

            def decoded(version):
                return json.loads(zlib.decompress(bytes(Version.objects.get(pk=version.pk).snapshot)))

            for target, kind_field in ((self.current, "type"), (self.previous, "question_type")):
                with (
                    patch.object(module, "VERSION_BATCH_SIZE", 1),
                    patch.object(module, "batches", failing_after_first_version_batch),
                    self.assertRaises(RuntimeError),
                ):
                    self.migrate(target)
                # The first batch committed before the failure; the retry must skip it.
                converted = [kind_field in decoded(version)["questions"][0] for version in versions]
                self.assertEqual(converted.count(True), 1)
                apps = self.migrate(target)
                Version = apps.get_model("quizzes", "QuizVersion")
                for version in versions:
                    questions = {q["id"]: q for q in decoded(version)["questions"]}
                    if kind_field == "type":
                        self.assertEqual(questions[str(multiple.pk)]["type"], "multiple_choice")
                        self.assertEqual(questions[str(tf.pk)]["type"], "true_false")
                        self.assertEqual([a["is_correct"] for a in questions[str(tf.pk)]["answers"]], [False, True])
                    else:
                        self.assertTrue(questions[str(multiple.pk)]["multiple"])
                        self.assertEqual(questions[str(tf.pk)]["question_type"], 2)
                        self.assertFalse(questions[str(tf.pk)]["tf_answer"])
        finally:
            self.migrate(self.current)
