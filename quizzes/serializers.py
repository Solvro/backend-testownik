from rest_framework import serializers

from quizzes.models import Folder, Quiz, SharedQuiz
from users.models import StudyGroup, User
from users.serializers import PublicUserSerializer, StudyGroupSerializer


class QuizSerializer(serializers.ModelSerializer):
    maintainer = PublicUserSerializer(read_only=True)
    can_edit = serializers.SerializerMethodField()
    collaborators = serializers.SerializerMethodField()

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
            "collaborators",
            "folder",
        ]
        read_only_fields = ["maintainer", "version", "can_edit", "folder"]

    def get_can_edit(self, obj) -> bool:
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.can_edit(request.user)
        return False

    def get_collaborators(self, obj):
        shared_quizzes = SharedQuiz.objects.filter(quiz=obj)
        collaborators = [
            {
                "user": shared_quiz.user.full_name if shared_quiz.user else None,
                "allow_edit": shared_quiz.allow_edit,
            }
            for shared_quiz in shared_quizzes
        ]
        return collaborators

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_anonymous and self.context.get("request").user != instance.maintainer:
            data["maintainer"] = None
        return data


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
            "version",
            "can_edit",
            "folder",
        ]
        read_only_fields = ["maintainer", "folder"]

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


class MoveQuizSerializer(serializers.Serializer):
    folder_id = serializers.UUIDField(allow_null=True)

    def validate_folder_id(self, value):
        if value:
            from .models import Folder

            user = self.context["request"].user

            if not Folder.objects.filter(id=value, owner=user).exists():
                raise serializers.ValidationError("The folder does not exist or you do not have access to it.")

        return value
