from rest_framework import serializers

from quizzes.models import Quiz, SharedQuiz, QuizCollaborator
from users.models import StudyGroup, User
from users.serializers import PublicUserSerializer, StudyGroupSerializer


class QuizCollaboratorSerializer(serializers.ModelSerializer):
    user = PublicUserSerializer(read_only=True)
    invited_by = PublicUserSerializer(read_only=True)
    status_name = serializers.SerializerMethodField()

    class Meta:
        model = QuizCollaborator
        fields = ['id', 'user', 'status', 'status_name', 'invited_by', 'created_at', 'updated_at']
        read_only_fields = ['user', 'invited_by', 'created_at', 'updated_at']

    def get_status_name(self, obj):
        return dict(QuizCollaborator._meta.get_field('status').choices)[obj.status]


class QuizSerializer(serializers.ModelSerializer):
    maintainer = PublicUserSerializer(read_only=True)
    collaborators = QuizCollaboratorSerializer(many=True, read_only=True)
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
            "questions",
            "collaborators",
            "can_edit",
        ]
        read_only_fields = ["maintainer", "version", "collaborators", "can_edit"]

    def get_can_edit(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.can_edit(request.user)
        return False

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if (
            instance.is_anonymous
            and not self.context.get("request").user == instance.maintainer
        ):
            data["maintainer"] = None
        return data


class QuizMetaDataSerializer(serializers.ModelSerializer):
    maintainer = PublicUserSerializer(read_only=True)

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
        ]
        read_only_fields = ["maintainer"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self.context.get("user")
        if instance.is_anonymous and not user == instance.maintainer:
            data["maintainer"] = None
        return data


class SharedQuizSerializer(serializers.ModelSerializer):
    quiz = QuizMetaDataSerializer(read_only=True)
    user = PublicUserSerializer(read_only=True)
    group = StudyGroupSerializer(source="study_group", read_only=True)
    quiz_id = serializers.PrimaryKeyRelatedField(
        queryset=Quiz.objects.all(), source="quiz", write_only=True
    )
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source="user", write_only=True, required=False
    )
    study_group_id = serializers.PrimaryKeyRelatedField(
        queryset=StudyGroup.objects.all(),
        source="study_group",
        write_only=True,
        required=False,
    )

    class Meta:
        model = SharedQuiz
        fields = ["id", "quiz", "quiz_id", "user", "user_id", "group", "study_group_id"]
        optional_fields = ["user_id", "study_group_id"]

    def validate(self, attrs):
        # Ensure that only one of `user_id` or `study_group_id` is provided
        user = attrs.get("user")
        study_group = attrs.get("study_group")
        if user and study_group:
            raise serializers.ValidationError(
                "Only one of 'user_id' or 'study_group_id' can be provided, not both."
            )
        if not user and not study_group:
            raise serializers.ValidationError(
                "You must provide either 'user_id' or 'study_group_id'."
            )
        return attrs
