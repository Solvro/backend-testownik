from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import BlogPostViewSet

router = DefaultRouter()
router.register("blog/posts", BlogPostViewSet, basename="blog-post")

urlpatterns = [
    path("", include(router.urls)),
]
