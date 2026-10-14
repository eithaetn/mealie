from typing import Any

from fastapi.exceptions import RequestValidationError
from pydantic import TypeAdapter, ValidationError
from rest_framework.request import Request

from mealie.schema.response.pagination import PaginationQuery


def pagination_query(request: Request) -> PaginationQuery:
    """Bind the existing pagination dependency's scalar query parameters.

    Only public aliases are accepted, unknown parameters are ignored, and the
    final value wins for repeated parameters, matching FastAPI's Depends binding.
    Keep field conversion errors separate from the model's own validators, whose
    exceptions previously propagated from the dependency constructor.
    """
    values: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    for name, field in PaginationQuery.model_fields.items():
        alias = field.alias or name
        if alias not in request.query_params:
            continue
        try:
            values[alias] = TypeAdapter(field.annotation).validate_python(request.query_params[alias])
        except ValidationError as exc:
            errors.extend({**error, "loc": ("query", alias, *error["loc"])} for error in exc.errors(include_url=False))
    if errors:
        raise RequestValidationError(errors)
    return PaginationQuery.model_validate(values)
