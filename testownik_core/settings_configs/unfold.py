from django.templatetags.static import static
from django.urls import reverse_lazy


def _item(title, icon, url_name):
    return {"title": title, "icon": icon, "link": reverse_lazy(url_name)}


def _group(title, items):
    group = {"separator": True, "collapsible": False, "items": items}
    if title is not None:
        group["title"] = title
    return group


def get_unfold_settings(frontend_url):
    return {
        "SITE_TITLE": "Testownik Solvro",
        "SITE_HEADER": "Testownik Solvro",
        "SITE_SUBHEADER": "by Antoni Czaplicki",
        "SITE_URL": frontend_url,
        "SITE_SYMBOL": "quiz",
        "SITE_ICON": {
            "light": lambda request: static("logo.svg"),
            "dark": lambda request: static("logo-dark.svg"),
        },
        "SITE_FAVICONS": [
            {
                "rel": "icon",
                "sizes": "32x32",
                "type": "image/svg+xml",
                "href": lambda request: static("logo.svg"),
            },
        ],
        "SHOW_HISTORY": True,
        "SHOW_VIEW_ON_SITE": True,
        "BORDER_RADIUS": "6px",
        "COLORS": {
            "base": {
                "50": "oklch(98.5% .002 247.839)",
                "100": "oklch(96.7% .003 264.542)",
                "200": "oklch(92.8% .006 264.531)",
                "300": "oklch(87.2% .01 258.338)",
                "400": "oklch(70.7% .022 261.325)",
                "500": "oklch(55.1% .027 264.364)",
                "600": "oklch(44.6% .03 256.802)",
                "700": "oklch(37.3% .034 259.733)",
                "800": "oklch(27.8% .033 256.848)",
                "900": "oklch(21% .034 264.665)",
                "950": "oklch(13% .028 261.692)",
            },
            "primary": {
                "50": "oklch(95.5% .02 250)",
                "100": "oklch(91% .04 250)",
                "200": "oklch(84% .08 250)",
                "300": "oklch(74% .14 250)",
                "400": "oklch(63% .19 250)",
                "500": "oklch(54% .22 250)",
                "600": "oklch(47% .21 250)",
                "700": "oklch(40% .18 250)",
                "800": "oklch(34% .15 250)",
                "900": "oklch(28% .11 250)",
                "950": "oklch(21% .08 250)",
            },
        },
        "SIDEBAR": {
            "show_search": True,
            # The sidebar holds everyday pages; "All applications" reaches every other model.
            "show_all_applications": True,
            "navigation": [
                _group(None, [_item("Dashboard", "dashboard", "admin:index")]),
                _group(
                    "Users",
                    [
                        _item("Users", "people", "admin:users_user_changelist"),
                        _item("Study groups", "groups", "admin:users_studygroup_changelist"),
                    ],
                ),
                _group(
                    "Quizzes",
                    [
                        _item("Quizzes", "quiz", "admin:quizzes_quiz_changelist"),
                        _item("Questions", "help", "admin:quizzes_question_changelist"),
                        _item("Uploaded images", "image", "admin:uploads_uploadedimage_changelist"),
                    ],
                ),
                _group(
                    "Content",
                    [
                        _item("Blog posts", "article", "admin:blog_blogpost_changelist"),
                        _item("Legal documents", "gavel", "admin:legal_legaldocumentversion_changelist"),
                        _item("Notifications", "notifications", "admin:notifications_notification_changelist"),
                    ],
                ),
                _group(
                    "AI",
                    [
                        _item("Conversations", "forum", "admin:ai_aichatconversation_changelist"),
                        _item("Daily usage", "bar_chart", "admin:ai_aiusagedailyaggregate_changelist"),
                        _item("Account limits", "speed", "admin:ai_aiaccountlimit_changelist"),
                        _item("Models and pricing", "paid", "admin:ai_aimodel_changelist"),
                    ],
                ),
                _group(
                    "System",
                    [
                        _item("Settings", "settings", "admin:constance_config_changelist"),
                        _item(
                            "Background tasks", "pending_actions", "admin:django_tasks_database_dbtaskresult_changelist"
                        ),
                    ],
                ),
            ],
        },
    }
