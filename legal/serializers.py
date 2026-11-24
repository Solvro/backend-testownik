from rest_framework import serializers

from .models import LegalDocumentVersion


class LegalDocumentVersionSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalDocumentVersion
        fields = ["id", "kind", "version", "effective_from", "requires_acceptance", "notify_users"]


class LegalDocumentVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalDocumentVersion
        fields = [*LegalDocumentVersionSummarySerializer.Meta.fields, "content"]


class LegalDocumentSerializer(serializers.Serializer):
    current = LegalDocumentVersionSerializer(allow_null=True)
    upcoming = LegalDocumentVersionSummarySerializer(allow_null=True)


class PendingNoticesSerializer(serializers.Serializer):
    terms = LegalDocumentVersionSummarySerializer(allow_null=True)
    privacy = LegalDocumentVersionSummarySerializer(allow_null=True)


class LegalAcceptanceCreateSerializer(serializers.Serializer):
    versions = serializers.PrimaryKeyRelatedField(
        queryset=LegalDocumentVersion.objects.published(),
        many=True,
        allow_empty=False,
    )
