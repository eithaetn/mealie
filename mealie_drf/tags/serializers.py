from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, TypeAdapter, ValidationError
from rest_framework import serializers

from mealie.schema.recipe.recipe_category import TagIn, TagMerge
from mealie.schema.response.pagination import PaginationQuery


def validate_tag_pagination(query: Any) -> PaginationQuery:
    values: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    # Depends(PaginationQuery) validates each query parameter first, then calls
    # the schema constructor. Constructor-level validator errors are server errors.
    for name, field in PaginationQuery.model_fields.items():
        alias = field.alias or name
        if alias not in query:
            continue
        try:
            values[name] = TypeAdapter(field.annotation).validate_python(query[alias])
        except ValidationError as exc:
            errors.extend({**error, "loc": ("query", alias)} for error in exc.errors(include_url=False))
    if errors:
        raise RequestValidationError(errors)
    return PaginationQuery(**values)


def validate_tag_input[T: BaseModel](schema: type[T], data: Any) -> T:
    try:
        # FastAPI enables attribute validation on its Pydantic request fields.
        return schema.model_validate(data, from_attributes=True)
    except ValidationError as exc:
        errors = [{**error, "loc": ("body", *error["loc"])} for error in exc.errors(include_url=False)]
        raise RequestValidationError(errors, body=data) from exc


class TagInputSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True, trim_whitespace=False)
    validated_model: TagIn

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        self.validated_model = validate_tag_input(TagIn, data)
        return self.validated_model.model_dump()


class TagMergeSerializer(serializers.Serializer):
    fromId = serializers.UUIDField(source="from_id")
    toId = serializers.UUIDField(source="to_id")
    validated_model: TagMerge

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        self.validated_model = validate_tag_input(TagMerge, data)
        return self.validated_model.model_dump()


class TagSerializer(serializers.Serializer):
    """Keep each operation's original Pydantic/SQLAlchemy output shape."""

    def to_representation(self, instance: Any) -> Any:
        return jsonable_encoder(instance)
