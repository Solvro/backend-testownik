from django.urls import path

from feedback.views import FeedbackAddView

urlpatterns = [
    path("feedback/send", FeedbackAddView.as_view(), name="feedback_add_api"),
]
