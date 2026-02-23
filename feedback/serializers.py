from rest_framework import serializers


class FeedbackSerializer(serializers.Serializer):
    name = serializers.CharField()
    email = serializers.EmailField(required=False, allow_blank=True)
    title = serializers.CharField()
    content = serializers.CharField()
    sendDiagnostics = serializers.CharField(required=False)
    diagnostic = serializers.CharField(required=False)
    reportType = serializers.CharField(required=False)
