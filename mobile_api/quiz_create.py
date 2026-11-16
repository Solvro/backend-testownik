"""Durable, first-party mobile creates without changing the legacy web contract."""

import hashlib
import json

from django.db import transaction
from django.db.models import Prefetch
from oauth2_provider.models import AccessToken
from rest_framework import serializers
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from quizzes.models import Answer, FolderType, Question, Quiz
from quizzes.serializers import QuizSerializer
from users.models import User

from .models import QuizCreateReceipt


class CreateRequestSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()


class ClientAnswerIDSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    image_url = serializers.CharField(max_length=512, required=False, allow_null=True, allow_blank=True)


class ClientQuestionIDsSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order = serializers.IntegerField(min_value=0, max_value=2147483647)
    image_url = serializers.CharField(max_length=512, required=False, allow_null=True, allow_blank=True)
    answers = ClientAnswerIDSerializer(many=True)
    quiz = serializers.JSONField(required=False)

    def validate(self, data):
        if "quiz" in data:
            raise serializers.ValidationError({"quiz": "The new quiz supplies the parent for each question."})
        return data


class ClientQuizIDsSerializer(serializers.Serializer):
    questions = ClientQuestionIDsSerializer(many=True)

    def validate(self, data):
        question_ids = [question["id"] for question in data["questions"]]
        answer_ids = [answer["id"] for question in data["questions"] for answer in question["answers"]]
        if len(set(question_ids)) != len(question_ids):
            raise serializers.ValidationError({"questions": "Question identifiers must be unique."})
        if len(set(answer_ids)) != len(answer_ids):
            raise serializers.ValidationError({"questions": "Answer identifiers must be unique across the quiz."})
        return data


_SNAPSHOT_FIELDS = (
    "version",
    "folder_id",
    "folder__owner_id",
    "folder__folder_type",
    "deleted_at",
    "archived_at",
    "creator_id",
)


def quiz_snapshot(quiz):
    return {
        "version": quiz.version,
        "folder_id": quiz.folder_id,
        "folder__owner_id": quiz.folder.owner_id,
        "folder__folder_type": quiz.folder.folder_type,
        "deleted_at": quiz.deleted_at,
        "archived_at": quiz.archived_at,
        "creator_id": quiz.creator_id,
    }


def receipt_response(receipt, user, request, *, replay):
    common = {"request_id": str(receipt.request_id)}
    if receipt.outcome == "rejected":
        return Response(
            {**common, "status": "rejected", "code": "validation_failed", "errors": receipt.validation_errors},
            status=400,
        )
    common.update({"created_version": receipt.created_version, "id_map": receipt.id_map})
    # Do not lock Quiz after User: account deletion takes the reverse order.
    # Content writers bump version in their transaction; retry a mixed snapshot.
    for _attempt in range(3):
        quiz = (
            (
                Quiz.objects.filter(pk=receipt.quiz_id)
                .select_related(
                    "folder", "folder__owner", "creator", "creator__photo_image", "creator__custom_photo_image"
                )
                .prefetch_related(
                    Prefetch("questions", queryset=Question.objects.select_related("image_upload")),
                    Prefetch("questions__answers", queryset=Answer.objects.select_related("image_upload")),
                )
                .first()
            )
            if receipt.quiz_id is not None
            else None
        )
        if quiz is not None and not user.owns_quiz_via_folder(quiz):
            return Response(
                {
                    "request_id": str(receipt.request_id),
                    "code": "create_access_lost",
                    "detail": "This quiz is no longer in your library.",
                },
                status=403,
            )
        if quiz is None or quiz.deleted_at is not None or quiz.folder.folder_type == FolderType.TRASH:
            return Response({**common, "status": "deleted", "quiz_id": str(receipt.original_quiz_id)}, status=410)
        before = quiz_snapshot(quiz)
        data = QuizSerializer(quiz, context={"request": request, "allow_includes": False}).data
        after = Quiz.objects.filter(pk=quiz.pk).values(*_SNAPSHOT_FIELDS).first()
        if before == after:
            return Response({**common, "status": "created", "quiz": data}, status=200 if replay else 201)
    return Response(
        {"request_id": str(receipt.request_id), "code": "quiz_changed", "detail": "The quiz changed. Retry saving."},
        status=409,
    )


class MobileQuizCreateView(APIView):
    parser_classes = [JSONParser]

    @transaction.atomic
    def post(self, request):
        token = request.auth
        if (
            not isinstance(token, AccessToken)
            or token.application_id is None
            or token.application.client_id != "testownik-mobile"
            or not token.allow_scopes(["quizzes:write"])
        ):
            return Response(
                {"code": "mobile_oauth_required", "detail": "Creating a mobile quiz requires the Testownik app."},
                status=403,
            )
        # This lock serializes duplicate operations on PostgreSQL. The DB
        # constraint remains a second barrier against duplicate receipts.
        user = User.objects.select_for_update().filter(pk=request.user.pk).first()
        # An authenticated guest can be upgraded/deleted before this lock is
        # acquired. Never recreate its identity or create under the new owner.
        if user is None or not user.is_active or user.is_banned:
            return Response(
                {"code": "account_unavailable", "detail": "Sign in again to save this quiz. Your draft is kept."},
                status=401,
            )
        envelope = CreateRequestSerializer(data=request.data)
        envelope.is_valid(raise_exception=True)
        request_id = envelope.validated_data["request_id"]
        # Preserve the raw immutable snapshot, including client IDs. Presence
        # distinguishes a missing payload from an explicitly null payload.
        snapshot = {"quiz": request.data["quiz"]} if "quiz" in request.data else {}
        try:
            canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)
            invalid_numbers = False
        except ValueError:
            # JSON exponents can overflow Python floats despite valid JSON syntax.
            # Fingerprint this invalid snapshot, then persist a rejection instead
            # of passing infinity to IntegerField or retrying a 500 forever.
            canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=True)
            invalid_numbers = True
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        receipt = (
            QuizCreateReceipt.objects.filter(user=user, request_id=request_id).select_related("quiz__folder").first()
        )
        if receipt is not None:
            if receipt.payload_hash != payload_hash:
                return Response({"code": "request_id_reused", "request_id": str(request_id)}, status=409)
            # Look up the result before revalidating mutable upload references.
            return receipt_response(receipt, user, request, replay=True)

        payload = request.data.get("quiz")
        id_map = {"questions": {}, "answers": {}}
        ids = ClientQuizIDsSerializer(data=payload)
        quiz = QuizSerializer(data=payload, context={"request": request, "created_id_map": id_map})
        if "quiz" not in request.data:
            errors = {"quiz": ["This field is required."]}
        elif invalid_numbers:
            errors = {"quiz": ["Numbers must be finite."]}
        elif not ids.is_valid():
            errors = ids.errors
        elif not quiz.is_valid():
            errors = quiz.errors
        else:
            errors = None
        if errors is not None:
            receipt = QuizCreateReceipt.objects.create(
                user=user,
                request_id=request_id,
                payload_hash=payload_hash,
                outcome="rejected",
                validation_errors=json.loads(json.dumps(errors)),
            )
            return receipt_response(receipt, user, request, replay=False)

        created = quiz.save(creator=user, folder=user.root_folder)
        receipt = QuizCreateReceipt.objects.create(
            user=user,
            request_id=request_id,
            payload_hash=payload_hash,
            outcome="created",
            quiz=created,
            original_quiz_id=created.pk,
            created_version=created.version,
            id_map=id_map,
        )
        return receipt_response(receipt, user, request, replay=False)
