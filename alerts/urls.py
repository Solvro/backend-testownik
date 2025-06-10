from rest_framework import routers

from alerts.views import AlertViewSet

router = routers.DefaultRouter()
router.register(r"alerts", AlertViewSet)

urlpatterns = router.urls