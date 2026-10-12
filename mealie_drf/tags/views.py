import asyncio
from functools import cached_property
from io import BytesIO
from typing import Any

from django.http import HttpRequest, HttpResponse
from fastapi import BackgroundTasks
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ValidationError
from rest_framework.renderers import BaseRenderer, JSONRenderer, StaticHTMLRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from sqlalchemy.exc import IntegrityError, NoResultFound
from starlette.datastructures import URL, QueryParams

from mealie.core.dependencies.dependencies import get_integration_id
from mealie.lang.providers import get_locale_config, get_locale_provider
from mealie.routes.organizers.controller_tags import TagController
from mealie.schema.recipe.recipe import RecipeTagPagination
from mealie.schema.recipe.recipe_category import RecipeTagResponse, TagOut
from mealie.services.event_bus_service.event_bus_service import EventBusService
from mealie_drf.context import get_request_context, get_request_session
from mealie_drf.crud import CrudAPIView
from mealie_drf.errors import MealieAPIError
from mealie_drf.tags.serializers import TagInputSerializer, TagMergeSerializer, TagSerializer, validate_tag_pagination
from mealie_drf.units.views import UnitJSONParser


def tag_slash_redirect(request: HttpRequest) -> HttpResponse:
    scope = {**request.scope, "path": request.scope["path"].rstrip("/")}
    original = RedirectResponse(str(URL(scope=scope)))
    response = HttpResponse(status=307, headers=dict(original.headers))
    del response["Content-Type"]
    return response


def tag_route_not_found(request: HttpRequest) -> HttpResponse:
    return HttpResponse(JSONResponse({"detail": "Not Found"}).body, status=404, content_type="application/json")


class TagResponse(Response):
    """Django closes responses after sending them; publish queued events then."""

    background: BackgroundTasks

    def close(self) -> None:
        try:
            asyncio.run(self.background())
        finally:
            super().close()


class TagJSONRenderer(JSONRenderer):
    def render(self, data: Any, accepted_media_type: str | None = None, renderer_context: dict | None = None) -> bytes:
        return JSONResponse(data).body


class TagBodyParser(UnitJSONParser):
    media_type = "*/*"

    def parse(self, stream: Any, media_type: str | None = None, parser_context: dict | None = None) -> Any:
        content_type = (media_type or "").split(";", 1)[0].strip().lower()
        if (
            not content_type
            or content_type == "application/json"
            or (content_type.startswith("application/") and content_type.endswith("+json"))
        ):
            try:
                return super().parse(stream, media_type, parser_context)
            except RequestValidationError:
                raise
            except Exception as exc:
                raise MealieAPIError(400, "There was an error parsing the body") from exc
        return stream.read()


class TagAPIView(CrudAPIView):
    renderer_classes = [TagJSONRenderer]
    parser_classes = [TagBodyParser]
    method_not_allowed_allow = "GET"

    def perform_content_negotiation(self, request: Request, force: bool = False) -> tuple[BaseRenderer, str]:
        # FastAPI returns JSON independently of the client's Accept header.
        return self.get_renderers()[0], "application/json"

    @property
    def default_response_headers(self) -> dict[str, str]:
        # FastAPI adds Allow only on 405, with the first matching route's method.
        return {}

    def finalize_response(self, request: Request, response: Response, *args: Any, **kwargs: Any) -> Response:
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.content_type == "text/plain; charset=utf-8":
            response.accepted_renderer = StaticHTMLRenderer()
            response.accepted_media_type = "text/plain"
        return response

    def input_serializer(self, serializer_type: type[TagInputSerializer] | type[TagMergeSerializer]) -> Any:
        data = self.request.data
        if data is None or self.request.META.get("CONTENT_LENGTH", "0") == "0":
            raise RequestValidationError(
                [{"type": "missing", "loc": ("body",), "msg": "Field required", "input": None}], body=None
            )
        serializer = serializer_type(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        if request.method.lower() not in self.http_method_names:
            raise MealieAPIError(405, "Method Not Allowed", headers={"Allow": self.method_not_allowed_allow})
        if request.method in {"POST", "PUT"}:
            # FastAPI reads the ASGI body even without Content-Length. Its strict
            # content-type policy leaves untyped bodies as bytes; DRF ignores them.
            http_request = request._request
            if not hasattr(http_request, "_body"):
                # Read the already-spooled ASGI body without Django's default
                # 2.5 MB body-property limit, which FastAPI does not impose.
                try:
                    http_request._body = http_request.read()
                except Exception as exc:
                    raise MealieAPIError(400, "There was an error parsing the body") from exc
                finally:
                    http_request._stream.close()
                http_request._stream = BytesIO(http_request._body)
            request.META["CONTENT_LENGTH"] = str(len(http_request.body))
            if not request.content_type:
                request.META["CONTENT_TYPE"] = "application/octet-stream"
        super().initial(request, *args, **kwargs)

    def handle_exception(self, exc: Exception) -> Response:
        if not isinstance(exc, ValidationError | IntegrityError | NoResultFound):
            try:
                return super().handle_exception(exc)
            except Exception:
                # Match FastAPI's production response for other uncaught errors.
                return self.server_error(exc)
        return self.server_error(exc)

    def server_error(self, exc: Exception) -> Response:
        # These errors escape the original tag controller. Do not apply the
        # shared adapter's SQLAlchemy 404/409 mapping to them.
        get_request_session(self.request).rollback()
        response = Response("Internal Server Error", status=500, content_type="text/plain; charset=utf-8")
        return response

    @cached_property
    def background(self) -> BackgroundTasks:
        return BackgroundTasks()

    @cached_property
    def controller(self) -> TagController:
        # Bind the existing controller's dependencies explicitly. DRF owns HTTP,
        # authentication and session lifetime; organizer operations remain shared.
        context = get_request_context(self.request)
        language = self.request.headers.get("Accept-Language")
        translator = get_locale_provider(language)
        controller = TagController(
            session=context.session,
            user=context.user,
            integration_id=asyncio.run(get_integration_id(token=self.request.auth)),
            translator=translator,
            locale_config=get_locale_config(language),
            event_bus=EventBusService(self.background, context.session, translator),
        )
        controller._repos = context.repos
        return controller

    def tag_response(self, value: Any, schema: type[BaseModel] | None = None, status: int = 200) -> Response:
        if schema is not None:
            value = schema.model_validate(value, from_attributes=True)
        # Serializer.data substitutes {} for a None instance; deletion is JSON null.
        response = TagResponse(
            TagSerializer(value, many=isinstance(value, list)).data if value is not None else None, status=status
        )
        response.background = self.background
        return response


class TagListView(TagAPIView):
    http_method_names = ["get", "post"]

    def get(self, request: Request) -> Response:
        query = QueryParams(request.META.get("QUERY_STRING", ""))
        pagination = validate_tag_pagination(query)
        value = asyncio.run(self.controller.get_all(q=pagination, search=query.get("search")))
        return self.tag_response(value, RecipeTagPagination)

    def post(self, request: Request) -> Response:
        serializer = self.input_serializer(TagInputSerializer)
        return self.tag_response(self.controller.create_one(serializer.validated_model), status=201)


class TagDetailView(TagAPIView):
    http_method_names = ["get", "put", "delete"]

    def get(self, request: Request, item_id: str) -> Response:
        return self.tag_response(self.controller.get_one(self.validated_id(item_id)), RecipeTagResponse)

    def put(self, request: Request, item_id: str) -> Response:
        errors = []
        try:
            tag_id = self.validated_id(item_id)
        except RequestValidationError as exc:
            errors.extend(exc.errors())
        try:
            serializer = self.input_serializer(TagInputSerializer)
        except RequestValidationError as exc:
            errors.extend(exc.errors())
        if errors:
            raise RequestValidationError(errors, body=request.data)
        return self.tag_response(self.controller.update_one(tag_id, serializer.validated_model), RecipeTagResponse)

    def delete(self, request: Request, item_id: str) -> Response:
        return self.tag_response(self.controller.delete_recipe_tag(self.validated_id(item_id)))


class TagEmptyView(TagDetailView):
    def get(self, request: Request, item_id: str = "empty") -> Response:
        return self.tag_response(self.controller.get_empty_tags())


class TagMergeView(TagDetailView):
    # FastAPI falls back to the UUID detail route for GET/PUT/DELETE /merge.
    http_method_names = ["get", "post", "put", "delete"]
    method_not_allowed_allow = "POST"

    def post(self, request: Request, item_id: str = "merge") -> Response:
        serializer = self.input_serializer(TagMergeSerializer)
        return self.tag_response(self.controller.merge_tags(serializer.validated_model), TagOut)


class TagSlugView(TagAPIView):
    http_method_names = ["get"]

    def get(self, request: Request, tag_slug: str) -> Response:
        return self.tag_response(asyncio.run(self.controller.get_one_by_slug(tag_slug)), RecipeTagResponse)
