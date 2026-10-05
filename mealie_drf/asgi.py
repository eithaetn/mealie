import os

from django.core.asgi import get_asgi_application

from mealie.app import app as fastapi_app
from mealie_drf.dispatcher import ASGIDispatcher

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mealie_drf.settings")
django_app = get_asgi_application()

# URL imports require Django setup to have completed.
from mealie_drf.urls import HEALTH_PATH  # noqa: E402

PORTED_HTTP_PREFIXES: tuple[str, ...] = ()

application = ASGIDispatcher(
    fastapi_app,
    django_app,
    ported_prefixes=PORTED_HTTP_PREFIXES,
    infrastructure_paths=(HEALTH_PATH,),
)
