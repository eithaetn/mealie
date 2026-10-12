"""HTTP configuration only: SQLAlchemy and Alembic retain database ownership."""

from mealie.core.config import get_app_settings

SECRET_KEY = get_app_settings().SESSION_SECRET
DEBUG = False
ALLOWED_HOSTS = ["*"]
ROOT_URLCONF = "mealie.drf.urls"
INSTALLED_APPS = ["rest_framework"]
MIDDLEWARE: list[str] = []
DATABASES: dict[str, dict[str, str]] = {}
USE_TZ = True
APPEND_SLASH = False
LOGGING_CONFIG = None
DATA_UPLOAD_MAX_MEMORY_SIZE = None
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["mealie.drf.renderers.MealieJSONRenderer"],
    "DEFAULT_CONTENT_NEGOTIATION_CLASS": "mealie.drf.negotiation.JSONContentNegotiation",
}
