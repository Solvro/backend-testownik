from django.urls import path

from grades.views import GetGradesView

urlpatterns = [
    path("grades/", GetGradesView.as_view(), name="get_grades"),
]
