from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from sqlalchemy.exc import IntegrityError, NoResultFound
from starlette.exceptions import HTTPException

from mealie.core.config import get_app_settings
from mealie.routes._base.mixins import is_unique_violation
from mealie.schema.response import ErrorResponse


class MealieAPIError(Exception):
    """HTTP error with an unchanged Mealie detail payload, including nested ErrorResponse data."""

    def __init__(self, status_code: int, detail: Any, headers: dict[str, str] | None = None) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


def bad_request(detail: Any) -> MealieAPIError:
    return MealieAPIError(400, detail)


def not_found(detail: Any = "Not Found") -> MealieAPIError:
    return MealieAPIError(404, detail)


def conflict(detail: Any) -> MealieAPIError:
    return MealieAPIError(409, detail)


def validate_input[T: BaseModel](schema: type[T], data: Any) -> T:
    """Mark Pydantic input failures explicitly; internal/output validation remains a server error."""
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        errors = [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()]
        raise RequestValidationError(errors, body=data) from exc


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, HTTPException | MealieAPIError):
        return Response({"detail": exc.detail}, status=exc.status_code, headers=exc.headers)

    if isinstance(exc, RequestValidationError):
        settings = get_app_settings()
        if not settings.PRODUCTION or settings.TESTING:
            message = str(exc).replace("\n", " ").replace("   ", " ")
            data = {"status_code": 422, "message": message, "data": None}
        else:
            data = {"detail": jsonable_encoder(exc.errors())}
        return Response(data, status=422)

    if isinstance(exc, NoResultFound | IntegrityError):
        status = 404 if isinstance(exc, NoResultFound) else 400
        message = "An unexpected error occurred."
        if isinstance(exc, IntegrityError) and is_unique_violation(exc):
            status = 409
            message = "This item already exists."
        return Response({"detail": ErrorResponse.respond(message, exception=str(exc))}, status=status)

    response = drf_exception_handler(exc, context)
    if response is not None and "detail" not in response.data:
        response.data = {"detail": response.data}
    return response
