from datetime import timedelta

from django.db import transaction
from rest_framework import serializers

from quizzes.models import (
    Answer,
    AnswerRecord,
    Folder,
    Question,
    Quiz,
    QuizSession,
    SharedQuiz,
)
from users.models import StudyGroup, User
from users.serializers import PublicUserSerializer, StudyGroupSerializer


class AnswerSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)

    class Meta:
        model = Answer
        fields = ["id", "order", "text", "image", "is_correct"]


class QuestionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    answers = AnswerSerializer(many=True)

    class Meta:
        model = Question
        fields = ["id", "order", "text", "image", "explanation", "multiple", "answers"]


class QuizSerializer(serializers.ModelSerializer):
    maintainer = PublicUserSerializer(read_only=True)
    can_edit = serializers.SerializerMethodField()
    questions = QuestionSerializer(many=True)

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "description",
            "maintainer",
            "visibility",
            "is_anonymous",
            "allow_anonymous",
            "version",
            "questions",
            "can_edit",
            "folder",
        ]
        read_only_fields = ["maintainer", "version", "can_edit", "folder"]

    def get_can_edit(self, obj) -> bool:
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.can_edit(request.user)
        return False

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else self.context.get("user")
        if instance.is_anonymous and user and user != instance.maintainer:
            data["maintainer"] = None
        return data

    @transaction.atomic
    def create(self, validated_data):
        """Create quiz with nested questions and answers in single transaction."""
        questions_data = validated_data.pop("questions", [])
        quiz = Quiz.objects.create(**validated_data)
        self._create_questions(quiz, questions_data)
        return quiz

    @transaction.atomic
    def update(self, instance, validated_data):
        """Update quiz fields and nested questions/answers in single transaction."""
        questions_data = validated_data.pop("questions", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if questions_data is not None:
            self._sync_questions(instance, questions_data)

        return Quiz.objects.prefetch_related("questions__answers").get(pk=instance.pk)

    def _create_questions(self, quiz, questions_data):
        """Bulk create questions and their answers."""
        if not questions_data:
            return

        questions_to_create = []
        questions_answers_data = []

        for q_data in questions_data:
            answers_data = q_data.pop("answers", [])
            q_data.pop("id", None)
            questions_to_create.append(Question(quiz=quiz, **q_data))
            questions_answers_data.append(answers_data)

        created_questions = Question.objects.bulk_create(questions_to_create)

        all_answers = []
        for question, answers_data in zip(created_questions, questions_answers_data):
            for a_data in answers_data:
                a_data.pop("id", None)
                all_answers.append(Answer(question=question, **a_data))

        if all_answers:
            Answer.objects.bulk_create(all_answers)

    def _bulk_create_answers(self, question, answers_data):
        """Bulk create answers for a single question."""
        if not answers_data:
            return
        for a in answers_data:
            a.pop("id", None)
        answers = [Answer(question=question, **a) for a in answers_data]
        Answer.objects.bulk_create(answers)

    def _has_changes(self, obj, data, fields):
        """Check if any field values differ between object and data."""
        return any(field in data and getattr(obj, field) != data[field] for field in fields)

    def _sync_questions(self, quiz, questions_data):
        """
        Synchronize questions with incoming data.

        - Existing questions (by ID) are updated
        - Missing questions are deleted
        - New questions (no ID or unknown ID) are created
        """
        existing_questions = {q.id: q for q in quiz.questions.prefetch_related("answers").all()}
        existing_ids = set(existing_questions.keys())
        incoming_ids = set()

        questions_to_update = []
        questions_to_create = []
        answers_to_sync = []

        question_fields = ["order", "text", "image", "explanation", "multiple"]

        for q_data in questions_data:
            answers_data = q_data.pop("answers", [])
            question_id = q_data.pop("id", None)

            if question_id and question_id in existing_ids:
                question = existing_questions[question_id]
                incoming_ids.add(question_id)
                answers_to_sync.append((question, answers_data))

                if self._has_changes(question, q_data, question_fields):
                    for attr, value in q_data.items():
                        setattr(question, attr, value)
                    questions_to_update.append(question)
            else:
                questions_to_create.append((q_data, answers_data))

        removed_ids = existing_ids - incoming_ids
        if removed_ids:
            Question.objects.filter(id__in=removed_ids).delete()

        if questions_to_update:
            Question.objects.bulk_update(questions_to_update, question_fields)

        self._batch_sync_answers(answers_to_sync)

        if questions_to_create:
            self._create_questions(
                quiz, [dict(**q_data, answers=answers_data) for q_data, answers_data in questions_to_create]
            )

    def _batch_sync_answers(self, answers_to_sync):
        """
        Batch sync answers for multiple questions in minimal DB queries.

        Collects all answer updates, creates, and deletes across all questions
        and executes them in 3 total queries (1 delete, 1 update, 1 create).
        """
        if not answers_to_sync:
            return

        all_answers_to_update = []
        all_answers_to_create = []
        all_answer_ids_to_delete = set()

        answer_fields = ["order", "text", "image", "is_correct"]

        for question, answers_data in answers_to_sync:
            existing_answers = {a.id: a for a in question.answers.all()}
            existing_ids = set(existing_answers.keys())
            incoming_ids = set()

            for a_data in answers_data:
                answer_id = a_data.pop("id", None)

                if answer_id and answer_id in existing_ids:
                    answer = existing_answers[answer_id]
                    incoming_ids.add(answer_id)

                    if self._has_changes(answer, a_data, answer_fields):
                        for attr, value in a_data.items():
                            setattr(answer, attr, value)
                        all_answers_to_update.append(answer)
                else:
                    all_answers_to_create.append(Answer(question=question, **a_data))

            all_answer_ids_to_delete.update(existing_ids - incoming_ids)

        if all_answer_ids_to_delete:
            Answer.objects.filter(id__in=all_answer_ids_to_delete).delete()

        if all_answers_to_update:
            Answer.objects.bulk_update(all_answers_to_update, answer_fields)

        if all_answers_to_create:
            Answer.objects.bulk_create(all_answers_to_create)


class QuizMetaDataSerializer(serializers.ModelSerializer):
    maintainer = PublicUserSerializer(read_only=True)
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "description",
            "maintainer",
            "visibility",
            "is_anonymous",
            "allow_anonymous",
            "created_at",
            "updated_at",
            "version",
            "can_edit",
            "folder",
        ]
        read_only_fields = ["maintainer", "created_at", "updated_at", "version", "can_edit", "folder"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else self.context.get("user")
        if instance.is_anonymous and user and user != instance.maintainer:
            data["maintainer"] = None
        return data

    def get_can_edit(self, obj) -> bool:
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.can_edit(request.user)
        return False


class SharedQuizSerializer(serializers.ModelSerializer):
    quiz = QuizMetaDataSerializer(read_only=True)
    user = PublicUserSerializer(read_only=True)
    group = StudyGroupSerializer(source="study_group", read_only=True)
    quiz_id = serializers.PrimaryKeyRelatedField(queryset=Quiz.objects.all(), source="quiz", write_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source="user", write_only=True, required=False
    )
    study_group_id = serializers.PrimaryKeyRelatedField(
        queryset=StudyGroup.objects.all(),
        source="study_group",
        write_only=True,
        required=False,
    )
    allow_edit = serializers.BooleanField(required=False, default=False)

    class Meta:
        model = SharedQuiz
        fields = [
            "id",
            "quiz",
            "quiz_id",
            "user",
            "user_id",
            "group",
            "study_group_id",
            "allow_edit",
        ]
        optional_fields = ["user_id", "study_group_id", "allow_edit"]

    def validate(self, attrs):
        user = attrs.get("user")
        study_group = attrs.get("study_group")

        # Never allow both user and study_group to be provided simultaneously
        if user and study_group:
            raise serializers.ValidationError("Only one of 'user_id' or 'study_group_id' can be provided, not both.")

        # For create operations (no instance) or when both fields are missing,
        # require at least one field to be provided
        if (not user and not study_group) and (
            not self.instance or (not self.instance.user and not self.instance.study_group)
        ):
            raise serializers.ValidationError("You must provide either 'user_id' or 'study_group_id'.")

        return attrs


class FolderSerializer(serializers.ModelSerializer):
    quizzes = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    subfolders = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = Folder
        fields = ["id", "name", "created_at", "parent", "quizzes", "subfolders"]
        read_only_fields = ["id", "created_at", "quizzes", "subfolders"]


class MoveFolderSerializer(serializers.Serializer):
    parent_id = serializers.UUIDField(allow_null=True)

    def validate_parent_id(self, value):
        user = self.context["request"].user
        folder_to_move = self.context["view"].get_object()

        if (
            Folder.objects.filter(owner=user, parent_id=value, name=folder_to_move.name)
            .exclude(id=folder_to_move.id)
            .exists()
        ):
            raise serializers.ValidationError(
                f"A folder with the name '{folder_to_move.name}' already exists in this destination."
            )

        if value:
            try:
                target_parent = Folder.objects.get(id=value, owner=user)
            except Folder.DoesNotExist:
                raise serializers.ValidationError(
                    "The destination folder does not exist or you do not have access to it."
                )

            if str(value) == str(folder_to_move.id):
                raise serializers.ValidationError("You cannot move a folder into itself.")

            current = target_parent
            while current:
                if current.id == folder_to_move.id:
                    raise serializers.ValidationError("You cannot move a folder into its own subfolder.")
                current = current.parent

        return value


class QuizSearchResultSerializer(serializers.ModelSerializer):
    """Serializer for search results."""

    maintainer = serializers.CharField(source="maintainer.full_name", read_only=True)

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "description",
            "maintainer",
            "is_anonymous",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else self.context.get("user")
        if instance.is_anonymous and user and user != instance.maintainer:
            data["maintainer"] = None
        return data


class DurationInSecondsField(serializers.Field):
    """Field for handling DurationField as total seconds."""

    def to_representation(self, value):
        if isinstance(value, timedelta):
            return value.total_seconds()
        return value

    def to_internal_value(self, data):
        try:
            return timedelta(seconds=float(data))
        except (ValueError, TypeError):
            self.fail("invalid")


class AnswerRecordSerializer(serializers.ModelSerializer):
    """Serializer for AnswerRecord."""
    class Meta:
        model = AnswerRecord
        fields = [
            "id",
            "question",
            "selected_answers",
            "was_correct",
            "answered_at",
        ]
        read_only_fields = ["id", "answered_at", "was_correct"]


class QuizSessionSerializer(serializers.ModelSerializer):
    """Serializer for QuizSession (new progress tracking)."""

    study_time = DurationInSecondsField(required=False)
    answers = AnswerRecordSerializer(many=True, read_only=True)

    class Meta:
        model = QuizSession
        fields = [
            "id",
            "quiz",
            "user",
            "current_question",
            "study_time",
            "is_active",
            "started_at",
            "ended_at",
            "answers",
        ]
        read_only_fields = ["id", "quiz", "user", "started_at", "ended_at"]


class MoveQuizSerializer(serializers.Serializer):
    folder_id = serializers.UUIDField(allow_null=True)

    def validate_folder_id(self, value):
        if value:
            user = self.context["request"].user

            if not Folder.objects.filter(id=value, owner=user).exists():
                raise serializers.ValidationError("The folder does not exist or you do not have access to it.")

        return value
