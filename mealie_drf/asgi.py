import os

from django.core.asgi import get_asgi_application
from starlette.middleware.cors import CORSMiddleware

from mealie.app import app as fastapi_app
from mealie.core.config import get_app_settings
from mealie_drf.dispatcher import ASGIDispatcher

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mealie_drf.settings")
django_app = get_asgi_application()
if not get_app_settings().PRODUCTION:
    # Match FastAPI's development CORS policy for the migrated boundary.
    django_app = CORSMiddleware(
        django_app,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# URL imports require Django setup to have completed.
from mealie_drf.urls import HEALTH_PATH  # noqa: E402

PORTED_HTTP_PREFIXES: tuple[str, ...] = ("/api/units",)

application = ASGIDispatcher(
    fastapi_app,
    django_app,
    ported_prefixes=PORTED_HTTP_PREFIXES,
    infrastructure_paths=(HEALTH_PATH,),
)
