"""Disposable local mobile integration environment. Never use in deployment."""

import os

from testownik_core.settings import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "10.0.2.2", "testserver"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("MOBILE_TEST_DB", "/tmp/testownik-mobile-integration.sqlite3"),
    }
}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CORS_ALLOWED_ORIGINS = [
    "http://localhost:8081",
    "http://localhost:8082",
    "http://127.0.0.1:8082",
    "http://127.0.0.1:8766",
]
JWT_COOKIE_SECURE = False
MEDIA_ROOT = "/tmp/testownik-mobile-media"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
