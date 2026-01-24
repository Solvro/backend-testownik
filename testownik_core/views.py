from django.urls import reverse
from django.views.generic import TemplateView


class ApiIndexView(TemplateView):
    template_name = "api_index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["apis"] = [
            {
                "url": reverse("scalar-ui"),
                "title": "Scalar API Reference",
                "badge": "Recommended",
                "badge_color": "bg-purple-600",
                "hover_color": "group-hover:text-purple-600",
                "description": "Modern, interactive API documentation with better search and request examples.",
                "image_light": "images/scalar_preview.png",
                "image_dark": "images/scalar_preview_dark.png",
            },
            {
                "url": reverse("swagger-ui"),
                "title": "Swagger UI",
                "badge": "Standard",
                "badge_color": "bg-blue-500",
                "hover_color": "group-hover:text-blue-500",
                "description": "Classic Swagger interface. Good for quick testing and familiarity.",
                "image_light": "images/swagger_preview.png",
                "image_dark": None,
            },
            {
                "url": reverse("redoc"),
                "title": "ReDoc",
                "badge": "Docs Only",
                "badge_color": "bg-orange-500",
                "hover_color": "group-hover:text-orange-500",
                "description": "Clean, three-panel design focused on readability and documentation.",
                "image_light": "images/redoc_preview.png",
                "image_dark": None,
            },
        ]
        return context
