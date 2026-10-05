from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponseBase
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from mealie.db.db_setup import session_context
from mealie_drf.authentication import MealieTokenAuthentication
from mealie_drf.context import get_request_session
from mealie_drf.errors import exception_handler


class MealieAPIView(APIView):
    """Minimal authenticated adapter for synchronous, non-streaming Mealie views.

    Session creation, authentication, view work, rendering, and closing all run on
    the sync view's thread. Repositories retain ownership of successful commits.
    """

    authentication_classes = [MealieTokenAuthentication]
    permission_classes: list[type[BasePermission]] = []

    def get_exception_handler(self) -> Callable[[Exception, dict[str, Any]], Response | None]:
        return exception_handler

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        with session_context() as session:
            request.mealie_session = session
            try:
                response = super().dispatch(request, *args, **kwargs)
                if isinstance(response, Response):
                    response.render()
                return response
            finally:
                # Do not leave a reusable request object pointing at a closed session.
                del request.mealie_session
                if hasattr(self, "request") and hasattr(self.request, "mealie_context"):
                    del self.request.mealie_context

    def handle_exception(self, exc: Exception) -> Response:
        get_request_session(self.request).rollback()
        return super().handle_exception(exc)
