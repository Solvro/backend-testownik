"""
Tests for client-generated question and answer IDs and the quiz version history.
"""

import uuid
from datetime import timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from quizzes.models import Answer, Question, Quiz, QuizVersion, QuizVersionSource
from quizzes.services.history import decode_snapshot, restore_payload
from users.models import User


def _answer(text, correct=False, order=1, answer_id=None):
    data = {"order": order, "text": text, "is_correct": correct}
    if answer_id is not None:
        data["id"] = answer_id
    return data


def _question(text, order=1, question_id=None, answers=None):
    data = {
        "order": order,
        "text": text,
        "multiple": False,
        "answers": answers or [_answer("Tak", True, 1), _answer("Nie", False, 2)],
    }
    if question_id is not None:
        data["id"] = question_id
    return data


class QuizHistoryTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="author@example.com", first_name="Ada", last_name="Autorka", student_number="111111"
        )
        self.other_user = User.objects.create(
            email="other@example.com", first_name="Olek", last_name="Obcy", student_number="222222"
        )
        self.client.force_authenticate(user=self.user)

    def create_quiz(self, questions, title="Quiz"):
        response = self.client.post(
            reverse("quiz-list"), {"title": title, "description": "", "questions": questions}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data

    def save(self, quiz_id, payload):
        response = self.client.patch(reverse("quiz-detail", args=[quiz_id]), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data

    def versions(self, quiz_id):
        response = self.client.get(reverse("quiz-versions", args=[quiz_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data


class ClientIdTestCase(QuizHistoryTestCase):
    def test_new_questions_and_answers_keep_client_ids(self):
        question_id, answer_ids = str(uuid.uuid4()), [str(uuid.uuid4()), str(uuid.uuid4())]
        quiz = self.create_quiz(
            [
                _question(
                    "Pierwsze",
                    question_id=question_id,
                    answers=[_answer("A", True, 1, answer_ids[0]), _answer("B", False, 2, answer_ids[1])],
                )
            ]
        )
        self.assertEqual(quiz["questions"][0]["id"], question_id)
        self.assertEqual([a["id"] for a in quiz["questions"][0]["answers"]], answer_ids)

    def test_saving_twice_updates_new_rows_instead_of_recreating_them(self):
        quiz = self.create_quiz([_question("Pierwsze")])
        new_question_id = str(uuid.uuid4())
        new_answer_id = str(uuid.uuid4())
        payload = {
            "questions": [
                *quiz["questions"],
                _question("Drugie", 2, new_question_id, [_answer("Nowa", True, 1, new_answer_id)]),
            ]
        }
        first = self.save(quiz["id"], payload)
        second = self.save(quiz["id"], payload)

        self.assertEqual(first["questions"][1]["id"], new_question_id)
        self.assertEqual(second["questions"][1]["id"], new_question_id)
        self.assertEqual(second["questions"][1]["answers"][0]["id"], new_answer_id)
        self.assertEqual(Question.objects.filter(quiz_id=quiz["id"]).count(), 2)

    def test_ids_used_elsewhere_or_repeated_are_replaced(self):
        other = Quiz.objects.create(title="Cudzy", creator=self.other_user, folder=self.other_user.root_folder)
        foreign = Question.objects.create(quiz=other, order=1, text="Cudze pytanie")
        foreign_answer = Answer.objects.create(question=foreign, order=1, text="Cudza", is_correct=True)
        repeated = str(uuid.uuid4())

        quiz = self.create_quiz(
            [
                _question("Przejęte?", 1, str(foreign.id), [_answer("x", True, 1, str(foreign_answer.id))]),
                _question("Pierwsze", 2, repeated),
                _question("Powtórzone", 3, repeated),
            ]
        )

        ids = [question["id"] for question in quiz["questions"]]
        self.assertNotEqual(ids[0], str(foreign.id))
        self.assertNotEqual(quiz["questions"][0]["answers"][0]["id"], str(foreign_answer.id))
        self.assertEqual(ids[1], repeated)
        self.assertNotEqual(ids[2], repeated)
        foreign.refresh_from_db()
        self.assertEqual(foreign.quiz, other)
        self.assertEqual(foreign.text, "Cudze pytanie")

    def test_an_answer_moved_between_questions_keeps_its_id(self):
        quiz = self.create_quiz([_question("Pierwsze", 1), _question("Drugie", 2)])
        first, second = quiz["questions"]
        moved = first["answers"][1]
        payload = {
            "questions": [
                {**first, "answers": [first["answers"][0]]},
                {**second, "answers": [*second["answers"], {**moved, "order": 3}]},
            ]
        }
        saved = self.save(quiz["id"], payload)
        self.assertIn(moved["id"], [a["id"] for a in saved["questions"][1]["answers"]])
        self.assertEqual(len(saved["questions"][0]["answers"]), 1)

    def test_recreating_a_question_from_an_echoed_response_works(self):
        """Clients send back question objects as the API returned them, with
        the `quiz` field; a removed question sent again must be recreated."""
        quiz = self.create_quiz([_question("Pierwsze", 1), _question("Drugie", 2)])
        first, second = quiz["questions"]
        self.save(quiz["id"], {"questions": [first]})
        saved = self.save(quiz["id"], {"questions": [first, second]})
        self.assertEqual([q["id"] for q in saved["questions"]], [first["id"], second["id"]])

    def test_bulk_create_keeps_client_ids(self):
        quiz = self.create_quiz([])
        question_id = str(uuid.uuid4())
        response = self.client.post(
            reverse("question-bulk-create"),
            {"quiz": quiz["id"], "questions": [_question("Z importu", 1, question_id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data[0]["id"], question_id)


class QuizVersionTestCase(QuizHistoryTestCase):
    def test_creating_a_quiz_records_its_first_version(self):
        quiz = self.create_quiz([_question("Pierwsze")])
        [version] = self.versions(quiz["id"])
        self.assertEqual(version["version"], 1)
        self.assertEqual(version["source"], QuizVersionSource.CREATE)
        self.assertEqual(version["question_count"], 1)
        self.assertEqual(version["author"]["id"], str(self.user.id))
        self.assertEqual(version["summary"], {"created": True, "added": 1})

    @mock.patch("quizzes.services.history.MERGE_WINDOW", timedelta(0))
    def test_each_change_records_a_version_with_a_summary(self):
        quiz = self.create_quiz([_question("Pierwsze", 1), _question("Drugie", 2)])
        first, second = quiz["questions"]
        saved = self.save(
            quiz["id"],
            {
                "title": "Nowy tytuł",
                "questions": [{**first, "text": "Pierwsze, poprawione"}, _question("Trzecie", 3)],
            },
        )

        newest, oldest = self.versions(quiz["id"])
        self.assertEqual(newest["version"], saved["version"])
        self.assertEqual(newest["source"], QuizVersionSource.EDITOR)
        self.assertEqual(newest["title"], "Nowy tytuł")
        self.assertEqual(newest["summary"], {"added": 1, "removed": 1, "changed": 1, "title": True})
        self.assertEqual(oldest["version"], 1)

    def test_saving_without_content_changes_records_nothing(self):
        quiz = self.create_quiz([_question("Pierwsze")])
        self.save(quiz["id"], {"visibility": 0})
        self.save(quiz["id"], {"questions": quiz["questions"]})
        self.assertEqual(len(self.versions(quiz["id"])), 1)

    def test_consecutive_saves_by_one_author_are_merged(self):
        quiz = self.create_quiz([_question("Pierwsze")])
        question = quiz["questions"][0]
        self.save(quiz["id"], {"questions": [{**question, "text": "Raz"}]})
        saved = self.save(quiz["id"], {"questions": [{**question, "text": "Dwa"}]})

        versions = self.versions(quiz["id"])
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["version"], saved["version"])
        self.assertEqual(versions[0]["summary"], {"changed": 1})

        # After a pause, the next save starts a new version.
        QuizVersion.objects.filter(quiz_id=quiz["id"]).update(updated_at=timezone.now() - timedelta(hours=1))
        self.save(quiz["id"], {"questions": [{**question, "text": "Trzy"}]})
        self.assertEqual(len(self.versions(quiz["id"])), 3)

    def test_older_quizzes_keep_their_content_from_before_history(self):
        quiz = Quiz.objects.create(title="Stary", creator=self.user, folder=self.user.root_folder, version=7)
        Question.objects.create(quiz=quiz, order=1, text="Stare pytanie")
        self.save(quiz.id, {"title": "Odświeżony"})

        newest, baseline = self.versions(quiz.id)
        self.assertEqual(baseline["source"], QuizVersionSource.BASELINE)
        self.assertEqual(baseline["version"], 7)
        self.assertIsNone(baseline["author"])
        self.assertEqual(baseline["title"], "Stary")
        self.assertEqual(baseline["summary"], {})
        self.assertEqual(newest["version"], 8)

    def test_opening_the_history_of_an_untouched_quiz_shows_its_current_content(self):
        quiz = Quiz.objects.create(title="Stary", creator=self.user, folder=self.user.root_folder, version=3)
        Question.objects.create(quiz=quiz, order=1, text="Stare pytanie")

        [baseline] = self.versions(quiz.id)
        self.assertEqual(baseline["source"], QuizVersionSource.BASELINE)
        self.assertEqual(baseline["version"], 3)
        self.assertEqual(baseline["question_count"], 1)
        # Opening it again adds nothing.
        self.assertEqual(len(self.versions(quiz.id)), 1)

        response = self.client.get(reverse("quiz-version-detail", args=[quiz.id, 3]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["content"]["questions"][0]["text"], "Stare pytanie")

    def test_question_endpoint_changes_are_recorded(self):
        quiz = self.create_quiz([_question("Pierwsze", 1), _question("Drugie", 2)])
        response = self.client.delete(reverse("question-detail", args=[quiz["questions"][1]["id"]]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        newest = self.versions(quiz["id"])[0]
        self.assertEqual(newest["source"], QuizVersionSource.QUESTION)
        self.assertEqual(newest["summary"], {"removed": 1})
        self.assertEqual(Quiz.objects.get(pk=quiz["id"]).version, newest["version"])

    def test_copying_a_quiz_records_its_first_version(self):
        quiz = self.create_quiz([_question("Pierwsze")])
        response = self.client.post(reverse("quiz-copy", args=[quiz["id"]]))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        [version] = self.versions(response.data["id"])
        self.assertEqual(version["source"], QuizVersionSource.COPY)

    def test_a_version_returns_its_content(self):
        quiz = self.create_quiz(
            [
                {
                    **_question("Z obrazkiem"),
                    "image_url": "https://example.com/obrazek.png",
                }
            ]
        )
        response = self.client.get(reverse("quiz-version-detail", args=[quiz["id"], 1]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = response.data["content"]
        self.assertEqual(content["title"], "Quiz")
        self.assertEqual(content["questions"][0]["id"], quiz["questions"][0]["id"])
        self.assertEqual(content["questions"][0]["image"], "https://example.com/obrazek.png")
        self.assertEqual([a["text"] for a in content["questions"][0]["answers"]], ["Tak", "Nie"])

        missing = self.client.get(reverse("quiz-version-detail", args=[quiz["id"], 99]))
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)

    @mock.patch("quizzes.services.history.MERGE_WINDOW", timedelta(0))
    def test_restoring_brings_back_removed_questions_with_their_ids(self):
        quiz = self.create_quiz([_question("Pierwsze", 1), _question("Drugie", 2)])
        first, second = quiz["questions"]
        self.save(quiz["id"], {"title": "Zmieniony", "questions": [{**first, "text": "Zmienione"}]})

        response = self.client.post(reverse("quiz-restore-version", args=[quiz["id"], 1]))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["title"], "Quiz")
        self.assertEqual(
            [(q["id"], q["text"]) for q in response.data["questions"]],
            [(first["id"], "Pierwsze"), (second["id"], "Drugie")],
        )
        self.assertEqual(
            [a["id"] for a in response.data["questions"][1]["answers"]], [a["id"] for a in second["answers"]]
        )

        newest = self.versions(quiz["id"])[0]
        self.assertEqual(newest["source"], QuizVersionSource.RESTORE)
        self.assertEqual(newest["restored_from"], 1)
        self.assertEqual(newest["version"], response.data["version"])
        self.assertEqual(len(self.versions(quiz["id"])), 3)

    @mock.patch("quizzes.services.history.MERGE_WINDOW", timedelta(0))
    def test_a_stale_client_cannot_reuse_a_version_number(self):
        """Two editors loaded the quiz at the same version; both saves must
        get their own version numbers instead of colliding."""
        quiz = self.create_quiz([_question("Pierwsze")])
        question = quiz["questions"][0]
        # Another editor's save moves the quiz on while this client holds v1.
        self.save(quiz["id"], {"questions": [{**question, "text": "Cudza zmiana"}]})
        stale = self.save(quiz["id"], {"title": "Spóźniony tytuł", "version": 1})
        versions = self.versions(quiz["id"])
        self.assertEqual([v["version"] for v in versions], [3, 2, 1])
        self.assertEqual(stale["version"], 3)
        self.assertEqual(Quiz.objects.get(pk=quiz["id"]).version, 3)

    @mock.patch("quizzes.services.history.MERGE_WINDOW", timedelta(0))
    def test_restoring_keeps_question_flags(self):
        quiz = self.create_quiz([_question("Pierwsze", 1), {**_question("Fiszka", 2), "is_flashcard": True}])
        first, flagged = quiz["questions"]
        self.save(
            quiz["id"], {"questions": [first, {**flagged, "text": "Zmiana", "is_ai_generated": True}]}
        )  # records v2 with both flags
        self.save(quiz["id"], {"questions": [first]})  # removes the flagged question

        response = self.client.post(reverse("quiz-restore-version", args=[quiz["id"], 2]))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        restored = Question.objects.get(id=quiz["questions"][1]["id"])
        self.assertTrue(restored.is_flashcard)
        self.assertTrue(restored.is_ai_generated)

    def test_only_editors_see_and_restore_history(self):
        quiz = self.create_quiz([_question("Pierwsze")])
        Quiz.objects.filter(pk=quiz["id"]).update(visibility=3)

        self.client.force_authenticate(user=self.other_user)
        for response in (
            self.client.get(reverse("quiz-versions", args=[quiz["id"]])),
            self.client.get(reverse("quiz-version-detail", args=[quiz["id"], 1])),
            self.client.post(reverse("quiz-restore-version", args=[quiz["id"], 1])),
        ):
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("quiz-versions", args=[quiz["id"]]))
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    @mock.patch("quizzes.services.history.MERGE_WINDOW", timedelta(0))
    @mock.patch("quizzes.services.history.MAX_VERSIONS", 3)
    def test_only_the_newest_versions_are_kept(self):
        quiz = self.create_quiz([_question("Pierwsze")])
        question = quiz["questions"][0]
        for text in ("A", "B", "C", "D"):
            self.save(quiz["id"], {"questions": [{**question, "text": text}]})
        versions = self.versions(quiz["id"])
        self.assertEqual(len(versions), 3)
        self.assertEqual(
            [
                decode_snapshot(QuizVersion.objects.get(quiz_id=quiz["id"], version=v["version"]).snapshot)[
                    "questions"
                ][0]["text"]
                for v in versions
            ],
            ["D", "C", "B"],
        )

    def test_restoring_drops_uploaded_images_which_no_longer_exist(self):
        snapshot = {
            "title": "T",
            "description": "",
            "questions": [
                {
                    "id": str(uuid.uuid4()),
                    "order": 1,
                    "text": "Q",
                    "explanation": "",
                    "multiple": False,
                    "question_type": 0,
                    "is_markdown_enabled": True,
                    "image_url": "https://example.com/zapas.png",
                    "image_upload": str(uuid.uuid4()),
                    "answers": [],
                }
            ],
        }
        question = restore_payload(snapshot)["questions"][0]
        self.assertIsNone(question["image_upload"])
        self.assertEqual(question["image_url"], "https://example.com/zapas.png")
