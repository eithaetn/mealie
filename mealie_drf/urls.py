from django.urls import path

from mealie_drf.views import health

HEALTH_PATH = "/_drf/health/"

urlpatterns = [path(HEALTH_PATH.lstrip("/"), health, name="drf-health")]
