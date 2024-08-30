from django.urls import path

from .views import index

app_name = "grades"

urlpatterns = [
    path("", index, name="index"),
]
