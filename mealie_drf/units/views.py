import inspect
import json
from contextvars import copy_context
from functools import cached_property
from typing import Any
from uuid import UUID

from django.http import HttpRequest, HttpResponse, HttpResponseBase, JsonResponse
from fastapi.exceptions import RequestValidationError
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.response import Response

from mealie.core.exceptions import mealie_registered_exceptions
from mealie.core.root_logger import get_logger
from mealie.lang.providers import get_locale_config, get_locale_provider, set_locale_context
from mealie.repos.repository_units import RepositoryUnit
from mealie.routes._base.mixins import HttpRepo
from mealie.schema import mapper
from mealie.schema.recipe.recipe_ingredient import CreateIngredientUnit, IngredientUnit, SaveIngredientUnit
from mealie.schema.response.pagination import PaginationQuery
from mealie.schema.response.responses import SuccessResponse
from mealie_drf.base import MealieAPIView
from mealie_drf.context import get_request_context
from mealie_drf.errors import MealieAPIError
from mealie_drf.units.serializers import (
    UnitInputSerializer,
    UnitMergeSerializer,
    UnitPaginationSerializer,
    UnitPathSerializer,
    UnitSerializer,
    validate_model,
)


def slash_redirect(request: HttpRequest, item_id: str | None = None) -> HttpResponse:
    target = request.path.removesuffix("/")
    if query := request.META.get("QUERY_STRING"):
        target += "?" + query
    return HttpResponse(status=307, headers={"Location": request.build_absolute_uri(target)})


def route_not_found(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"detail": "Not Found"}, status=404)


class UnitJSONParser(JSONParser):
    def parse(self, stream: Any, media_type: str | None = None, parser_context: dict | None = None) -> Any:
        try:
            return json.load(stream)
        except json.JSONDecodeError as exc:
            raise RequestValidationError(
                [
                    {
                        "type": "json_invalid",
                        "loc": ("body", exc.pos),
                        "msg": "JSON decode error",
                        "input": {},
                        "ctx": {"error": exc.msg},
                    }
                ]
            ) from exc


class UnitAPIView(MealieAPIView):
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

    @cached_property
    def repo(self) -> RepositoryUnit:
        return get_request_context(self.request).repos.ingredient_units

    @cached_property
    def crud(self) -> HttpRepo[CreateIngredientUnit, IngredientUnit, CreateIngredientUnit]:
        translator = get_locale_provider(self.request.headers.get("Accept-Language"))

        def message(error: type[Exception]) -> str:
            return mealie_registered_exceptions(translator).get(error, translator.t("generic.server-error"))

        return HttpRepo(self.repo, get_logger(), message)

    def unit_response(self, unit: IngredientUnit | None, status: int = 200) -> Response:
        response = Response(UnitSerializer(unit).data if unit is not None else None, status=status)
        if unit is not None and (updated_at := response.data.get("updatedAt")):
            response["last-modified"] = updated_at
            response["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    def validated_id(self, item_id: str) -> UUID:
        serializer = UnitPathSerializer(data={"item_id": item_id})
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data["item_id"]


class UnitListView(UnitAPIView):
    http_method_names = ["get", "post"]

    def get(self, request: Request) -> Response:
        # FastAPI's Depends(PaginationQuery) binds camelCase query aliases, not snake_case.
        query = {
            field.alias or name: request.query_params[field.alias or name]
            for name, field in PaginationQuery.model_fields.items()
            if (field.alias or name) in request.query_params
        }
        pagination = validate_model(PaginationQuery, query, ("query",))
        result = self.repo.page_all(pagination, override=IngredientUnit, search=request.query_params.get("search"))
        # The original controller uses its local router URL, which is /units.
        result.set_pagination_guides("/units", pagination.model_dump())
        return Response(UnitPaginationSerializer(result).data)

    def post(self, request: Request) -> Response:
        serializer = UnitInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = mapper.cast(
            serializer.validated_model, SaveIngredientUnit, group_id=get_request_context(request).group_id
        )
        return self.unit_response(self.crud.create_one(data), status=201)


class UnitDetailView(UnitAPIView):
    http_method_names = ["get", "put", "delete"]

    def get(self, request: Request, item_id: str) -> Response:
        return self.unit_response(self.crud.get_one(self.validated_id(item_id)))

    def put(self, request: Request, item_id: str) -> Response:
        unit_id = self.validated_id(item_id)
        serializer = UnitInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.unit_response(self.crud.update_one(serializer.validated_model, unit_id))

    def delete(self, request: Request, item_id: str) -> Response:
        return self.unit_response(self.crud.delete_one(self.validated_id(item_id)))


class UnitMergeView(UnitDetailView):
    def put(self, request: Request, item_id: str = "merge") -> Response:
        serializer = UnitMergeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_model
        try:
            self.repo.merge(data.from_unit, data.to_unit)
        except Exception as exc:
            get_logger().error(exc)
            raise MealieAPIError(500, "Failed to merge units") from exc
        return Response(SuccessResponse.respond("Successfully merged units"))
