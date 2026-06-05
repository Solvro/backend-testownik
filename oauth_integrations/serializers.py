from rest_framework import serializers


class AuthorizationParameterValueField(serializers.Field):
    def to_internal_value(self, data):
        if isinstance(data, str):
            return data
        if isinstance(data, list) and all(isinstance(item, str) for item in data):
            return data
        raise serializers.ValidationError("Must be a string or a list of strings.")

    def to_representation(self, value):
        return value


class AuthorizationDecisionSerializer(serializers.Serializer):
    authorization_params = serializers.DictField(
        child=AuthorizationParameterValueField(),
    )
    scopes = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        default=list,
        required=False,
    )
    allow = serializers.BooleanField()


class AuthorizedAppSerializer(serializers.Serializer):
    client_id = serializers.CharField()
    oauth_application_id = serializers.CharField()
    client_name = serializers.CharField()
    client_uri = serializers.URLField(allow_blank=True)
    logo_uri = serializers.URLField(allow_blank=True)
    created = serializers.DateTimeField()
    scopes = serializers.CharField()
