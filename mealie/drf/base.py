import json
from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync
from django.http import HttpRequest
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import UUID4, BaseModel, TypeAdapter, ValidationError
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from sqlalchemy.orm import Session
from starlette.datastructures import FormData
from starlette.exceptions import HTTPException

from mealie.core.api_error import APIError
from mealie.core.config import get_app_settings
from mealie.db.db_setup import session_context
from mealie.drf.authentication import MealieAuthentication, MealieUserPermission
from mealie.drf.forms import parse_form


class MealieAPIView(APIView):
    # Explicit method lists preserve FastAPI's HEAD/OPTIONS behaviour.
    http_method_names: list[str] = []
    body_schema: type[BaseModel] | None = None
    parsed_body: Any = None
    form_body = False
    parsed_form: FormData | None = None

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        # Routing in FastAPI rejects the method before evaluating dependencies.
        self.format_kwarg = self.get_format_suffix(**kwargs)
        if request.method.lower() not in self.http_method_names:
            raise MethodNotAllowed(request.method)
        if self.form_body:
            self.parsed_form = async_to_sync(parse_form)(request._request)
        if self.body_schema is not None:
            # FastAPI decodes JSON before authentication dependencies but validates
            # the model afterwards. Keep that ordering, including malformed JSON.
            raw = request.body
            content_type = request.content_type or "application/json"
            is_json = content_type == "application/json" or (
                content_type.startswith("application/") and content_type.endswith("+json")
            )
            if raw and is_json:
                try:
                    self.parsed_body = json.loads(raw)
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
                except UnicodeDecodeError as exc:
                    raise APIError(400, "There was an error parsing the body") from exc
            else:
                self.parsed_body = raw or None
        super().initial(request, *args, **kwargs)

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, RequestValidationError):
            return self.validation_response(exc.errors())
        if isinstance(exc, (APIError, HTTPException)):
            return Response({"detail": exc.detail}, status=exc.status_code, headers=exc.headers)
        if isinstance(exc, MethodNotAllowed):
            return Response({"detail": "Method Not Allowed"}, status=405)
        return super().handle_exception(exc)

    def finalize_response(self, request: Request, response: Response, *args: Any, **kwargs: Any) -> Response:
        if response.status_code != 405:
            self.headers.pop("Allow", None)
        return super().finalize_response(request, response, *args, **kwargs)

    def validation_error(self, exc: ValidationError, location: str = "body", field: str | None = None) -> Response:
        prefix = (location, field) if field else (location,)
        errors = [{**error, "loc": (*prefix, *error["loc"])} for error in exc.errors(include_url=False)]
        return self.validation_response(errors)

    def validation_response(self, errors: list) -> Response:
        settings = get_app_settings()
        if not settings.PRODUCTION or settings.TESTING:
            message = str(RequestValidationError(errors)).replace("\n", " ").replace("   ", " ")
            return Response({"status_code": 422, "message": message, "data": None}, status=422)
        return Response({"detail": jsonable_encoder(errors)}, status=422)

    def validated_body[T: BaseModel](self, schema: type[T]) -> T:
        if self.parsed_body is None:
            raise RequestValidationError(
                [{"type": "missing", "loc": ("body",), "msg": "Field required", "input": None}]
            )
        return schema.model_validate(self.parsed_body, from_attributes=True)


class SessionAPIView(MealieAPIView):
    db: Session

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Response:
        with session_context() as session:
            self.db = session
            try:
                return super().dispatch(request, *args, **kwargs)
            finally:
                if self.parsed_form is not None:
                    async_to_sync(self.parsed_form.close)()


class UserAPIView(SessionAPIView):
    authentication_classes = [MealieAuthentication]
    permission_classes = [MealieUserPermission]

    def validated_id(self, value: UUID) -> UUID:
        try:
            return TypeAdapter(UUID4).validate_python(str(value))
        except ValidationError as exc:
            raise RequestValidationError(
                [{**error, "loc": ("path", "id")} for error in exc.errors(include_url=False)]
            ) from exc
