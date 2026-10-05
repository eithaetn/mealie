import inspect
from contextvars import copy_context
from typing import Any
from uuid import UUID

from django.http import HttpRequest, HttpResponseBase
from fastapi.exceptions import RequestValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from mealie.lang.providers import get_locale_config, get_locale_provider, set_locale_context
from mealie_drf.base import MealieAPIView
from mealie_drf.errors import MealieAPIError
from mealie_drf.units.serializers import UnitPathSerializer
from mealie_drf.units.views import UnitJSONParser


class CrudAPIView(MealieAPIView):
    parser_classes = [UnitJSONParser]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        if request.method.lower() not in self.http_method_names:
            raise MealieAPIError(405, "Method Not Allowed", headers={"Allow": ", ".join(self.allowed_methods)})
        # FastAPI parses declared JSON bodies before resolving authentication.
        if request.method in {"POST", "PUT"}:
            _ = request.data
        super().initial(request, *args, **kwargs)

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        # Repository standardization uses locale context. Isolate it so reused Django
        # worker threads cannot leak a previous request's language into the next one.
        return copy_context().run(self.dispatch_with_locale, request, *args, **kwargs)

    def dispatch_with_locale(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        language = request.headers.get("Accept-Language")
        set_locale_context(get_locale_provider(language), get_locale_config(language))
        return super().dispatch(request, *args, **kwargs)

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, RequestValidationError):
            handler = getattr(self, self.request.method.lower())
            exc = RequestValidationError(
                exc.errors(),
                body=exc.body,
                endpoint_ctx={
                    "file": inspect.getsourcefile(handler),
                    "line": inspect.getsourcelines(handler)[1],
                    "function": handler.__name__,
                    "path": f"{self.request.method} {self.request.path}",
                },
            )
        return super().handle_exception(exc)

    def validated_id(self, item_id: str) -> UUID:
        serializer = UnitPathSerializer(data={"item_id": item_id})
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data["item_id"]
