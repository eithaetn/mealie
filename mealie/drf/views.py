from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from mealie.db.db_setup import session_context
from mealie.drf.base import MealieAPIView
from mealie.services.app_info_service import AppInfoService


class PublicAppView(MealieAPIView):
    # These three endpoints have always been public. Protected endpoints use
    # UserAPIView and explicitly enforce Mealie's authentication and permissions.
    authentication_classes: list[type[BaseAuthentication]] = []
    permission_classes: list[type[BasePermission]] = []
    http_method_names = ["get"]


class AppInfoView(PublicAppView):
    def get(self, request: Request) -> Response:
        with session_context() as session:
            result = AppInfoService().get_info(session)
        return Response(result.model_dump(mode="json", by_alias=True))


class AppStartupInfoView(PublicAppView):
    def get(self, request: Request) -> Response:
        with session_context() as session:
            result = AppInfoService().get_startup_info(session)
        return Response(result.model_dump(mode="json", by_alias=True))


class AppThemeView(PublicAppView):
    def get(self, request: Request) -> Response:
        result = AppInfoService().get_theme()
        return Response(
            result.model_dump(mode="json", by_alias=True), headers={"Cache-Control": "public, max-age=604800"}
        )
