from django.urls import path

from .views import (
    LegalAcceptanceView,
    LegalDocumentVersionDetailView,
    LegalDocumentVersionListView,
    LegalDocumentView,
    PendingNoticesView,
)

urlpatterns = [
    path("legal/acceptances/", LegalAcceptanceView.as_view(), name="legal-acceptances"),
    path("legal/pending/", PendingNoticesView.as_view(), name="legal-pending"),
    path("legal/<str:kind>/", LegalDocumentView.as_view(), name="legal-document"),
    path("legal/<str:kind>/versions/", LegalDocumentVersionListView.as_view(), name="legal-document-versions"),
    path(
        "legal/<str:kind>/versions/<int:version>/",
        LegalDocumentVersionDetailView.as_view(),
        name="legal-document-version",
    ),
]
