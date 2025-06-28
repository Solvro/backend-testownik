from django.urls import path

from grades.views import get_grades

urlpatterns = [
    path("grades/", get_grades, name="get_grades"),
]
