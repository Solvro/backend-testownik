from django.urls import path

from wrapped.views import get_wrapped, get_wrapped_global

urlpatterns = [
    path("wrapped/", get_wrapped, name="get_wrapped"),
    path("wrapped/global/", get_wrapped_global, name="get_wrapped_global"),
]
