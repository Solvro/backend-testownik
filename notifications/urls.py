from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import NotificationViewSet

router = DefaultRouter()
router.register("notifications", NotificationViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
