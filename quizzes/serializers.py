from rest_framework import serializers

from quizzes.models import SharedQuiz, Quiz
from users.serializers import PublicUserSerializer


class QuizSerializer(serializers.ModelSerializer):
    maintainer = PublicUserSerializer(read_only=True)

    class Meta:
        model = Quiz
        fields = ["id", "title", "description", "maintainer", "visibility", "is_anonymous", "version", "questions"]
        read_only_fields = ["maintainer", "version"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_anonymous and not self.context.get("request").user == instance.maintainer:
            data["maintainer"] = None
        return data

class QuizMetaDataSerializer(serializers.ModelSerializer):
    maintainer = PublicUserSerializer(read_only=True)

    class Meta:
        model = Quiz
        fields = ["id", "title", "description", "maintainer", "visibility", "is_anonymous", "version"]
        read_only_fields = ["maintainer"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_anonymous and not self.context.get("request").user == instance.maintainer:
            data["maintainer"] = None
        return data

class SharedQuizSerializer(serializers.ModelSerializer):
    class Meta:
        model = SharedQuiz
        fields = ["id", "quiz", "user", "study_group"]
