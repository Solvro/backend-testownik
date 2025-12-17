from rest_framework import serializers

from quizzes.models import Quiz, SharedQuiz
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
        ]
        read_only_fields = ["maintainer", "version", "can_edit"]

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
        ]
        read_only_fields = ["maintainer"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self.context.get("user")
        if instance.is_anonymous and user != instance.maintainer:
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
