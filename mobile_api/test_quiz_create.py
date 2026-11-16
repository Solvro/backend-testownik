"""Durable create regression tests; fixtures live only in Django's disposable DB."""

import copy
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from oauth2_provider.models import AccessToken, RefreshToken, get_application_model
from rest_framework.test import APIClient

from quizzes.models import Answer, Folder, FolderType, Question, Quiz, QuizSession
from quizzes.serializers import QuizSerializer
from uploads.models import UploadedImage
from users.models import User, UserSettings
from users.serializers import UserTokenObtainPairSerializer
from users.services import delete_account, migrate_guest_to_user

from .models import QuizCreateReceipt


class MobileQuizCreateTests(TestCase):
    url = "/api/mobile/quizzes/"

    def setUp(self):
        call_command("register_mobile_oauth", verbosity=0)
        self.application = get_application_model().objects.get(client_id="testownik-mobile")
        self.user = User.objects.create_user(email="create@example.invalid", password="fixture-password")
        self.client = APIClient()
        self.authenticate()
        self.payload = {
            "request_id": str(uuid.uuid4()),
            "quiz": {
                "title": "Durable fixture",
                "visibility": 0,
                "questions": [
                    {
                        "id": str(uuid.uuid4()),
                        "text": "Pick the answer",
                        "order": 0,
                        "multiple": True,
                        "answers": [
                            {"id": str(uuid.uuid4()), "text": "Correct", "is_correct": True, "order": 0},
                            {"id": str(uuid.uuid4()), "text": "Other", "is_correct": False, "order": 1},
                        ],
                    },
                    {"id": str(uuid.uuid4()), "text": "Empty flashcard", "order": 1, "answers": []},
                ],
            },
        }

    def authenticate(self, user=None, application=None, scope="quizzes:write"):
        token = AccessToken.objects.create(
            user=user or self.user,
            application=application or self.application,
            token="opaque-" + str(uuid.uuid4()),
            scope=scope,
            expires=timezone.now() + timedelta(minutes=5),
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        return token

    def post(self, payload=None):
        return self.client.post(self.url, payload if payload is not None else self.payload, format="json")

    def assert_no_writes(self):
        self.assertEqual(Quiz.objects.count(), 0)
        self.assertEqual(QuizCreateReceipt.objects.count(), 0)

    def test_create_replay_returns_complete_stable_regenerated_id_map(self):
        first = self.post()
        self.assertEqual(first.status_code, 201, first.data)
        second = self.post()
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data, second.data)
        self.assertEqual(Quiz.objects.count(), 1)
        self.assertEqual(Question.objects.count(), 2)
        self.assertEqual(Answer.objects.count(), 2)
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)
        self.assertEqual(first.data["request_id"], self.payload["request_id"])
        self.assertEqual(first.data["status"], "created")
        ids = first.data["id_map"]
        self.assertEqual(set(ids["questions"]), {q["id"] for q in self.payload["quiz"]["questions"]})
        self.assertEqual(
            set(ids["answers"]), {a["id"] for q in self.payload["quiz"]["questions"] for a in q["answers"]}
        )
        self.assertEqual(
            set(ids["questions"].values()), {str(pk) for pk in Question.objects.values_list("pk", flat=True)}
        )
        self.assertEqual(set(ids["answers"].values()), {str(pk) for pk in Answer.objects.values_list("pk", flat=True)})
        self.assertTrue(all(client != server for mapping in ids.values() for client, server in mapping.items()))
        self.assertTrue(Question.objects.get(text="Pick the answer").multiple)

    def test_replay_current_quiz_keeps_original_created_version(self):
        first = self.post()
        Quiz.objects.filter(pk=first.data["quiz"]["id"]).update(version=8, title="Edited elsewhere")
        replay = self.post()
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.data["quiz"]["version"], 8)
        self.assertEqual(replay.data["quiz"]["title"], "Edited elsewhere")
        self.assertEqual(replay.data["created_version"], first.data["created_version"])
        self.assertEqual(replay.data["id_map"], first.data["id_map"])

    def test_replay_retries_mixed_content_snapshot_without_changing_original_identity(self):
        first = self.post()
        original = QuizSerializer.to_representation
        serializations = []

        def change_once(serializer, instance):
            data = original(serializer, instance)
            serializations.append(instance.version)
            if len(serializations) == 1:
                Quiz.objects.filter(pk=instance.pk).update(version=7, title="Concurrent edit")
                Question.objects.filter(quiz=instance, order=0).update(text="Changed question")
            return data

        with patch.object(QuizSerializer, "to_representation", autospec=True, side_effect=change_once):
            replay = self.post()
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(serializations, [1, 7])
        self.assertEqual(replay.data["quiz"]["version"], 7)
        self.assertEqual(replay.data["quiz"]["title"], "Concurrent edit")
        self.assertEqual(replay.data["quiz"]["questions"][0]["text"], "Changed question")
        self.assertEqual(replay.data["created_version"], first.data["created_version"])
        self.assertEqual(replay.data["id_map"], first.data["id_map"])

    def test_continuously_changed_replay_is_retryable_and_retains_receipt(self):
        first = self.post()
        original = QuizSerializer.to_representation
        serializations = []

        def change_always(serializer, instance):
            data = original(serializer, instance)
            serializations.append(instance.version)
            Quiz.objects.filter(pk=instance.pk).update(version=instance.version + 1)
            return data

        with patch.object(QuizSerializer, "to_representation", autospec=True, side_effect=change_always):
            response = self.post()
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "quiz_changed")
        self.assertEqual(len(serializations), 3)
        self.assertNotIn("quiz", response.data)
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)
        self.assertEqual(Quiz.objects.count(), 1)
        stable = self.post()
        self.assertEqual(stable.status_code, 200)
        self.assertEqual(stable.data["quiz"]["id"], first.data["quiz"]["id"])
        self.assertEqual(stable.data["created_version"], first.data["created_version"])

    def test_transfer_during_serialization_discards_previously_authorized_content(self):
        self.post()
        other = User.objects.create_user(email="during-replay@example.invalid")
        original = QuizSerializer.to_representation

        def transfer(serializer, instance):
            data = original(serializer, instance)
            Quiz.objects.filter(pk=instance.pk).update(folder=other.root_folder)
            return data

        with patch.object(QuizSerializer, "to_representation", autospec=True, side_effect=transfer):
            response = self.post()
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(set(response.data), {"request_id", "code", "detail"})
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)

    def test_image_heavy_replay_uses_bounded_upload_queries(self):
        image = UploadedImage.objects.create(
            image="fixture.png", original_filename="fixture.png", content_type="image/png", file_size=1
        )
        first = self.post()
        quiz = Quiz.objects.get(pk=first.data["quiz"]["id"])
        questions = Question.objects.bulk_create(
            [Question(quiz=quiz, text="Image fixture", order=index + 2, image_upload=image) for index in range(25)]
        )
        Answer.objects.bulk_create(
            [Answer(question=question, text="Image answer", order=0, image_upload=image) for question in questions]
        )
        with CaptureQueriesContext(connection) as queries:
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["quiz"]["questions"]), 27)
        upload_reads = [query for query in queries if 'FROM "uploads_uploadedimage"' in query["sql"]]
        self.assertLessEqual(len(upload_reads), 2, "Replay must not fetch every question/answer image separately")

    def test_create_and_replay_ignore_user_state_include_side_effects(self):
        initial_settings = UserSettings.objects.count()
        for expected in (201, 200):
            response = self.client.post(
                self.url + "?include=current_session,user_settings", self.payload, format="json"
            )
            self.assertEqual(response.status_code, expected, response.data)
            self.assertNotIn("current_session", response.data["quiz"])
            self.assertNotIn("user_settings", response.data["quiz"])
            self.assertEqual(QuizSession.objects.count(), 0)
            self.assertEqual(UserSettings.objects.count(), initial_settings)

    def test_delete_or_trash_during_serialization_discards_content_and_returns_tombstone(self):
        original = QuizSerializer.to_representation
        for kind in ("hard", "trash"):
            self.payload["request_id"] = str(uuid.uuid4())
            first = self.post()

            def remove(serializer, instance):
                data = original(serializer, instance)
                if kind == "hard":
                    instance.delete()
                else:
                    Quiz.objects.filter(pk=instance.pk).update(deleted_at=timezone.now())
                return data

            with (
                self.subTest(kind=kind),
                patch.object(QuizSerializer, "to_representation", autospec=True, side_effect=remove),
            ):
                response = self.post()
                self.assertEqual(response.status_code, 410, response.data)
                self.assertNotIn("quiz", response.data)
                self.assertEqual(response.data["quiz_id"], first.data["quiz"]["id"])
                self.assertEqual(response.data["id_map"], first.data["id_map"])

    def test_json_numeric_overflow_is_durably_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload["quiz"]["questions"][0]["order"] = "overflow-number"
        raw = json.dumps(payload).replace('"overflow-number"', "1e999")
        first = self.client.post(self.url, data=raw, content_type="application/json")
        self.assertEqual(first.status_code, 400, first.data)
        self.assertEqual(first.data["status"], "rejected")
        self.assertEqual(first.data, self.client.post(self.url, data=raw, content_type="application/json").data)
        self.assertEqual(Quiz.objects.count(), 0)
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)

    def test_same_request_changed_payload_conflicts_without_writes(self):
        first = self.post()
        self.payload["quiz"]["title"] = "Changed"
        response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "request_id_reused")
        self.assertEqual(Quiz.objects.get().title, first.data["quiz"]["title"])
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)

    def test_json_key_order_does_not_change_request_hash(self):
        first = self.post()
        payload = copy.deepcopy(self.payload)
        payload["quiz"] = dict(reversed(list(payload["quiz"].items())))
        self.assertEqual(self.post(payload).data, first.data)

    def test_same_uuid_is_scoped_to_authenticated_owner(self):
        first = self.post()
        other = User.objects.create_user(email="other@example.invalid")
        self.authenticate(other)
        second = self.post()
        self.assertEqual(second.status_code, 201, second.data)
        self.assertNotEqual(second.data["quiz"]["id"], first.data["quiz"]["id"])
        self.assertEqual(QuizCreateReceipt.objects.count(), 2)
        self.assertEqual(Quiz.objects.get(pk=second.data["quiz"]["id"]).folder.owner_id, other.pk)

    def test_deleted_quiz_replays_tombstone_and_never_recreates(self):
        first = self.post()
        Quiz.objects.get().delete()
        response = self.post()
        self.assertEqual(response.status_code, 410, response.data)
        self.assertEqual(response.data["status"], "deleted")
        self.assertEqual(response.data["quiz_id"], first.data["quiz"]["id"])
        self.assertEqual(response.data["id_map"], first.data["id_map"])
        self.assertEqual(Quiz.objects.count(), 0)
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)

    def test_soft_deleted_and_trash_quiz_replay_tombstones(self):
        for kind in ("deleted_at", "trash"):
            with self.subTest(kind=kind):
                self.payload["request_id"] = str(uuid.uuid4())
                first = self.post()
                quiz = Quiz.objects.get(pk=first.data["quiz"]["id"])
                if kind == "deleted_at":
                    quiz.deleted_at = timezone.now()
                else:
                    quiz.folder = Folder.objects.get(owner=self.user, folder_type=FolderType.TRASH)
                quiz.save()
                response = self.post()
                self.assertEqual(response.status_code, 410)
                self.assertEqual(response.data["quiz_id"], str(quiz.pk))
        self.assertEqual(Quiz.objects.count(), 2)

    def test_transferred_quiz_denies_replay_without_content_and_retains_receipt(self):
        self.post()
        other = User.objects.create_user(email="new-owner@example.invalid")
        Quiz.objects.update(folder=other.root_folder)
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "create_access_lost")
        self.assertNotIn("quiz", response.data)
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)
        Quiz.objects.update(folder=self.user.root_folder)
        self.assertEqual(self.post().status_code, 200)

    def test_invalid_shapes_and_ids_are_durably_rejected(self):
        invalids = [None, [], {}, {"title": "No questions"}, copy.deepcopy(self.payload["quiz"])]
        invalids[-1]["questions"][0]["id"] = "bad-id"
        missing_id = copy.deepcopy(self.payload["quiz"])
        del missing_id["questions"][0]["answers"][0]["id"]
        invalids.append(missing_id)
        for order in (None, -1, 2147483648):
            bad_order = copy.deepcopy(self.payload["quiz"])
            if order is None:
                del bad_order["questions"][0]["order"]
            else:
                bad_order["questions"][0]["order"] = order
            invalids.append(bad_order)
        for quiz in invalids:
            with self.subTest(quiz_type=type(quiz).__name__):
                payload = {"request_id": str(uuid.uuid4()), "quiz": quiz}
                first = self.post(payload)
                self.assertEqual(first.status_code, 400, first.data)
                self.assertEqual(first.data["status"], "rejected")
                self.assertEqual(first.data, self.post(payload).data)
        self.assertEqual(Quiz.objects.count(), 0)
        self.assertEqual(QuizCreateReceipt.objects.count(), len(invalids))

    def test_missing_payload_rejection_differs_from_explicit_null(self):
        payload = {"request_id": self.payload["request_id"]}
        first = self.post(payload)
        self.assertEqual(first.status_code, 400)
        self.assertEqual(first.data["status"], "rejected")
        self.assertEqual(self.post({**payload, "quiz": None}).status_code, 409)

    def test_duplicate_ids_and_nested_parent_are_rejected(self):
        for kind in ("questions", "answers", "parent"):
            payload = copy.deepcopy(self.payload)
            payload["request_id"] = str(uuid.uuid4())
            questions = payload["quiz"]["questions"]
            if kind == "questions":
                questions[1]["id"] = questions[0]["id"]
            elif kind == "answers":
                questions[1]["answers"] = [copy.deepcopy(questions[0]["answers"][0])]
            else:
                questions[0]["quiz"] = str(uuid.uuid4())
            with self.subTest(kind=kind):
                response = self.post(payload)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.data["status"], "rejected")
        self.assertEqual(Quiz.objects.count(), 0)

    def test_image_url_column_bounds_are_durably_validated(self):
        prefix = "https://example.invalid/"
        for target in ("question", "answer"):
            payload = copy.deepcopy(self.payload)
            payload["request_id"] = str(uuid.uuid4())
            question = payload["quiz"]["questions"][0]
            item = question if target == "question" else question["answers"][0]
            item["image_url"] = prefix + "a" * (513 - len(prefix))
            with self.subTest(target=target):
                first = self.post(payload)
                self.assertEqual(first.status_code, 400, first.data)
                self.assertEqual(first.data["status"], "rejected")
                self.assertEqual(self.post(payload).data, first.data)
                item["image_url"] = item["image_url"][:-1]
                payload["request_id"] = str(uuid.uuid4())
                self.assertEqual(self.post(payload).status_code, 201)
        self.assertEqual(Quiz.objects.count(), 2)

    def test_transferred_then_trashed_quiz_does_not_disclose_tombstone(self):
        self.post()
        other = User.objects.create_user(email="trashed-owner@example.invalid")
        Quiz.objects.update(folder=Folder.objects.get(owner=other, folder_type=FolderType.TRASH))
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "create_access_lost")
        self.assertNotIn("quiz_id", response.data)
        self.assertNotIn("id_map", response.data)
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)

    def test_rejection_is_retained_if_mutable_upload_becomes_valid(self):
        upload_id = uuid.uuid4()
        self.payload["quiz"]["questions"][0]["image_upload"] = str(upload_id)
        first = self.post()
        self.assertEqual(first.status_code, 400)
        UploadedImage.objects.create(
            pk=upload_id, image="fixture.png", original_filename="fixture.png", content_type="image/png", file_size=1
        )
        self.assertEqual(self.post().data, first.data)
        self.assertEqual(Quiz.objects.count(), 0)
        self.payload["quiz"]["title"] = "Corrected snapshot"
        self.assertEqual(self.post().status_code, 409)

    def test_foreign_upload_is_a_retained_validation_rejection(self):
        other = User.objects.create_user(email="private-upload@example.invalid")
        image = UploadedImage.objects.create(
            image="private.png",
            original_filename="private.png",
            content_type="image/png",
            file_size=1,
            uploaded_by=other,
        )
        self.payload["quiz"]["questions"][0]["image_upload"] = str(image.pk)
        first = self.post()
        self.assertEqual(first.status_code, 400, first.data)
        self.assertEqual(first.data["status"], "rejected")
        self.assertEqual(first.data["code"], "validation_failed")
        self.assertEqual(self.post().data, first.data)
        self.assertEqual(Quiz.objects.count(), 0)
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)

    def test_success_replays_before_revalidating_deleted_upload(self):
        image = UploadedImage.objects.create(
            image="fixture.png",
            original_filename="fixture.png",
            content_type="image/png",
            file_size=1,
            uploaded_by=self.user,
        )
        self.payload["quiz"]["questions"][0]["image_upload"] = str(image.pk)
        first = self.post()
        self.assertEqual(first.status_code, 201, first.data)
        image.delete()
        replay = self.post()
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(replay.data["quiz"]["id"], first.data["quiz"]["id"])
        self.assertEqual(Quiz.objects.count(), 1)

    def test_unknown_quiz_key_cannot_borrow_another_quiz_image_allowance(self):
        from quizzes.models import SharedQuiz

        other = User.objects.create_user(email="image-collaborator@example.invalid")
        target = Quiz.objects.create(title="Shared target", creator=other, folder=other.root_folder, visibility=1)
        SharedQuiz.objects.create(quiz=target, user=self.user, allow_edit=True)
        self.assertTrue(target.can_edit(self.user))
        image = UploadedImage.objects.create(
            image="shared.png", original_filename="shared.png", content_type="image/png", file_size=1, uploaded_by=other
        )
        Question.objects.create(quiz=target, text="Existing", order=0, image_upload=image)
        self.payload["quiz"]["quiz"] = str(target.pk)
        self.payload["quiz"]["questions"][0]["image_upload"] = str(image.pk)
        first = self.post()
        self.assertEqual(first.status_code, 400, first.data)
        self.assertEqual(first.data["status"], "rejected")
        self.assertEqual(self.post().data, first.data)
        self.assertEqual(Quiz.objects.count(), 1)
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)

    def test_unexpected_response_failure_rolls_back_quiz_and_receipt(self):
        with (
            patch("mobile_api.quiz_create.receipt_response", side_effect=RuntimeError("fixture failure")),
            self.assertRaises(RuntimeError),
        ):
            self.post()
        self.assert_no_writes()
        self.assertEqual(Question.objects.count(), 0)
        self.assertEqual(self.post().status_code, 201)

    def test_invalid_request_id_does_not_allocate_receipt(self):
        self.payload["request_id"] = "bad"
        self.assertEqual(self.post().status_code, 400)
        self.assert_no_writes()

    def test_unauthenticated_jwt_session_third_party_and_readonly_denied(self):
        self.client.credentials()
        self.assertEqual(self.post().status_code, 401)
        token = UserTokenObtainPairSerializer.get_token(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        self.assertEqual(self.post().status_code, 403)
        self.client.credentials()
        self.client.force_login(self.user)
        self.assertEqual(self.post().status_code, 403)
        self.client.logout()
        application = get_application_model().objects.create(
            client_id="other-app", name="Other", client_type="public", authorization_grant_type="authorization-code"
        )
        self.authenticate(application=application)
        self.assertEqual(self.post().status_code, 403)
        self.authenticate(scope="quizzes:read")
        self.assertEqual(self.post().status_code, 403)
        self.assert_no_writes()

    def test_banned_database_user_denied_before_receipt(self):
        self.authenticate()
        self.user.is_banned = True
        self.user.save(update_fields=["is_banned"])
        self.assertIn(self.post().status_code, (401, 403))
        self.assert_no_writes()

    def test_database_constraint_rejects_duplicate_operation(self):
        self.post()
        receipt = QuizCreateReceipt.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            QuizCreateReceipt.objects.create(
                user=self.user,
                request_id=receipt.request_id,
                payload_hash=receipt.payload_hash,
                outcome="created",
                quiz=receipt.quiz,
            )
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)

    def test_expired_revoked_and_disabled_credentials_cannot_replay_content(self):
        self.post()
        token = self.authenticate()
        token.expires = timezone.now() - timedelta(seconds=1)
        token.save(update_fields=["expires"])
        self.assertEqual(self.post().status_code, 401)
        token = self.authenticate()
        token.delete()
        self.assertEqual(self.post().status_code, 401)
        self.authenticate()
        self.user.is_banned = True
        self.user.save(update_fields=["is_banned"])
        response = self.post()
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("quiz", response.data)
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)
        self.assertEqual(Quiz.objects.count(), 1)

    def test_account_delete_cascades_receipts(self):
        self.post()
        delete_account(self.user)
        self.assertEqual(QuizCreateReceipt.objects.count(), 0)

    def test_legacy_jwt_and_guest_create_without_ids_still_works(self):
        for user in (self.user, User.objects.create_guest_user()):
            token = UserTokenObtainPairSerializer.get_token(user)
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
            quiz = copy.deepcopy(self.payload["quiz"])
            for question in quiz["questions"]:
                del question["id"]
                for answer in question["answers"]:
                    del answer["id"]
            response = self.client.post("/api/quizzes/", quiz, format="json")
            self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Quiz.objects.count(), 2)
        self.assertEqual(QuizCreateReceipt.objects.count(), 0)

    def test_guest_lost_ack_replay_returns_one_quiz_and_stable_identity(self):
        guest = User.objects.create_guest_user()
        self.authenticate(guest)
        first = self.post()
        self.assertEqual(first.status_code, 201, first.data)
        # The response may be lost; a restarted client resubmits its immutable journal.
        self.authenticate(guest)
        replay = self.post()
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(first.data, replay.data)
        self.assertEqual(Quiz.objects.count(), 1)
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)
        self.assertEqual(QuizCreateReceipt.objects.get().user, guest)
        edited = copy.deepcopy(self.payload)
        edited["quiz"]["title"] = "Changed retry"
        conflict = self.post(edited)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.data["code"], "request_id_reused")
        self.assertEqual(Quiz.objects.count(), 1)

    def test_upgrade_does_not_adopt_guest_receipt_or_overwrite_target_uuid_collision(self):
        target_created = self.post()
        self.assertEqual(target_created.status_code, 201)
        target_receipt = QuizCreateReceipt.objects.filter(user=self.user).values().get()
        guest = User.objects.create_guest_user()
        guest_id = guest.pk
        access = self.authenticate(guest)
        refresh = RefreshToken.objects.create(
            user=guest, application=self.application, access_token=access, token="guest-refresh-fixture"
        )
        guest_payload = copy.deepcopy(self.payload)
        guest_payload["quiz"]["title"] = "Guest collision fixture"
        guest_created = self.post(guest_payload)
        self.assertEqual(guest_created.status_code, 201, guest_created.data)
        self.assertEqual(QuizCreateReceipt.objects.count(), 2)
        self.assertTrue(migrate_guest_to_user(str(guest_id), self.user))
        self.assertFalse(User.objects.filter(pk=guest_id).exists())
        self.assertFalse(AccessToken.objects.filter(pk=access.pk).exists())
        self.assertFalse(RefreshToken.objects.filter(pk=refresh.pk).exists())
        self.assertEqual(QuizCreateReceipt.objects.filter(user=self.user).values().get(), target_receipt)
        self.assertEqual(QuizCreateReceipt.objects.count(), 1)
        migrated = Quiz.objects.get(pk=guest_created.data["quiz"]["id"])
        self.assertEqual(migrated.creator, self.user)
        self.assertEqual(migrated.folder, self.user.root_folder)
        self.assertEqual(self.post(guest_payload).status_code, 401)
        self.authenticate()
        target_replay = self.post()
        self.assertEqual(target_replay.status_code, 200)
        self.assertEqual(target_replay.data["quiz"]["id"], target_created.data["quiz"]["id"])
        self.assertEqual(target_replay.data["id_map"], target_created.data["id_map"])
        self.assertEqual(target_replay.data["created_version"], target_created.data["created_version"])
        conflict = self.post(guest_payload)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.data["code"], "request_id_reused")
        self.assertEqual(Quiz.objects.count(), 2)

    def test_failed_upgrade_rolls_back_guest_receipt_and_can_replay(self):
        guest = User.objects.create_guest_user()
        access = self.authenticate(guest)
        first = self.post()
        self.assertEqual(first.status_code, 201, first.data)
        receipt = QuizCreateReceipt.objects.values().get()
        with patch.object(User, "delete", side_effect=RuntimeError("Synthetic upgrade rollback")):
            self.assertFalse(migrate_guest_to_user(str(guest.pk), self.user))
        self.assertEqual(QuizCreateReceipt.objects.values().get(), receipt)
        self.assertTrue(AccessToken.objects.filter(pk=access.pk).exists())
        created = Quiz.objects.get()
        self.assertEqual(created.creator, guest)
        self.assertEqual(created.folder, guest.root_folder)
        replay = self.post()
        self.assertEqual(replay.status_code, 200, replay.data)
        self.assertEqual(replay.data, first.data)

    def test_guest_deleted_after_authentication_is401_without_receipt(self):
        guest = User.objects.create_guest_user()
        token = self.authenticate(guest)
        authenticated_user = copy.copy(guest)
        delete_account(guest)
        # Model the race after authentication succeeded but before the row lock.
        self.client.force_authenticate(user=authenticated_user, token=token)
        self.client.raise_request_exception = False
        response = self.post()
        self.assertEqual(response.status_code, 401, getattr(response, "data", None))
        self.assertEqual(response.data["code"], "account_unavailable")
        self.assert_no_writes()

    def test_guest_jwt_durable_denial_cannot_fall_back_inside_endpoint(self):
        guest = User.objects.create_guest_user()
        token = UserTokenObtainPairSerializer.get_token(guest)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "mobile_oauth_required")
        self.assert_no_writes()

    def test_guest_banned_after_authentication_is_denied_before_any_write(self):
        guest = User.objects.create_guest_user()
        token = self.authenticate(guest)
        User.objects.filter(pk=guest.pk).update(is_banned=True)
        # Authentication observed an active principal, then moderation won the lock.
        self.client.force_authenticate(user=guest, token=token)
        response = self.post()
        self.assertEqual(response.status_code, 401, response.data)
        self.assertEqual(response.data["code"], "account_unavailable")
        self.assert_no_writes()
