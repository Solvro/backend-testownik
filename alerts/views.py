from rest_framework import mixins, viewsets
from rest_framework.permissions import AllowAny

from alerts.models import Alert
from alerts.serializers import AlertSerializer


class AlertViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Alert.objects.filter(active=True)
    serializer_class = AlertSerializer
    permission_classes = [AllowAny]
    pagination_class = None
