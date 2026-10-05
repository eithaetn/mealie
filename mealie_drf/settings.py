"""Minimal Django configuration; Mealie retains ownership of persistence."""

from mealie.core.config import get_app_settings

SECRET_KEY = get_app_settings().SECRET
DEBUG = False
ALLOWED_HOSTS = ["*"]
ROOT_URLCONF = "mealie_drf.urls"
INSTALLED_APPS = ["rest_framework", "drf_spectacular"]
MIDDLEWARE: list[str] = []
DATABASES: dict[str, dict[str, str]] = {}
USE_TZ = True
APPEND_SLASH = False

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
