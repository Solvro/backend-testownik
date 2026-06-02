from django.templatetags.static import static
from django.urls import reverse_lazy


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
            "show_all_applications": True,
            "navigation": [
                {
                    "title": "Navigation",
                    "separator": True,
                    "items": [
                        {
                            "title": "Dashboard",
                            "icon": "dashboard",
                            "link": reverse_lazy("admin:index"),
                        },
                    ],
                },
                {
                    "title": "Users",
                    "separator": True,
                    "collapsible": True,
                    "items": [
                        {
                            "title": "Users",
                            "icon": "people",
                            "link": reverse_lazy("admin:users_user_changelist"),
                        },
                        {
                            "title": "Study Groups",
                            "icon": "groups",
                            "link": reverse_lazy("admin:users_studygroup_changelist"),
                        },
                        {
                            "title": "Terms",
                            "icon": "calendar_month",
                            "link": reverse_lazy("admin:users_term_changelist"),
                        },
                        {
                            "title": "Email Login Tokens",
                            "icon": "key",
                            "link": reverse_lazy("admin:users_emaillogintoken_changelist"),
                        },
                    ],
                },
                {
                    "title": "Quizzes",
                    "separator": True,
                    "collapsible": True,
                    "items": [
                        {
                            "title": "Quizzes",
                            "icon": "quiz",
                            "link": reverse_lazy("admin:quizzes_quiz_changelist"),
                        },
                        {
                            "title": "Questions",
                            "icon": "help",
                            "link": reverse_lazy("admin:quizzes_question_changelist"),
                        },
                        {
                            "title": "Sessions",
                            "icon": "play_circle",
                            "link": reverse_lazy("admin:quizzes_quizsession_changelist"),
                        },
                        {
                            "title": "Shared Quizzes",
                            "icon": "share",
                            "link": reverse_lazy("admin:quizzes_sharedquiz_changelist"),
                        },
                        {
                            "title": "Folders",
                            "icon": "folder",
                            "link": reverse_lazy("admin:quizzes_folder_changelist"),
                        },
                    ],
                },
                {
                    "title": "Uploads",
                    "separator": True,
                    "collapsible": True,
                    "items": [
                        {
                            "title": "Uploaded Images",
                            "icon": "image",
                            "link": reverse_lazy("admin:uploads_uploadedimage_changelist"),
                        },
                    ],
                },
                {
                    "title": "OAuth",
                    "separator": True,
                    "collapsible": True,
                    "items": [
                        {
                            "title": "Applications",
                            "icon": "apps",
                            "link": reverse_lazy("admin:oauth2_provider_application_changelist"),
                        },
                        {
                            "title": "Access Tokens",
                            "icon": "token",
                            "link": reverse_lazy("admin:oauth2_provider_accesstoken_changelist"),
                        },
                    ],
                },
                {
                    "title": "System",
                    "separator": True,
                    "collapsible": True,
                    "items": [
                        {
                            "title": "Constance",
                            "icon": "settings",
                            "link": reverse_lazy("admin:constance_config_changelist"),
                        },
                    ],
                },
            ],
        },
    }
