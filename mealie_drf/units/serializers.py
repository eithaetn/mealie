from typing import Any
from uuid import UUID

from fastapi.exceptions import RequestValidationError
from pydantic import UUID4, BaseModel, TypeAdapter, ValidationError
from rest_framework import serializers

from mealie.schema.recipe.recipe_ingredient import CreateIngredientUnit, IngredientUnit, MergeUnit


def validate_model[T: BaseModel](schema: type[T], data: Any, location: tuple[str, ...]) -> T:
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        errors = [{**error, "loc": (*location, *error["loc"])} for error in exc.errors(include_url=False)]
        raise RequestValidationError(errors, body=data) from exc


class UnitAliasSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True, trim_whitespace=False)


class UnitInputSerializer(serializers.Serializer):
    """Keep Mealie's aliases, coercion, defaults, and cross-field normalization authoritative."""

    id = serializers.UUIDField(required=False, allow_null=True)
    name = serializers.CharField(allow_blank=True, trim_whitespace=False)
    pluralName = serializers.CharField(source="plural_name", required=False, allow_null=True, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    extras = serializers.JSONField(required=False, allow_null=True)
    fraction = serializers.BooleanField(required=False)
    abbreviation = serializers.CharField(required=False, allow_blank=True)
    pluralAbbreviation = serializers.CharField(
        source="plural_abbreviation", required=False, allow_blank=True, allow_null=True
    )
    useAbbreviation = serializers.BooleanField(source="use_abbreviation", required=False)
    aliases = UnitAliasSerializer(many=True, required=False)
    standardQuantity = serializers.FloatField(source="standard_quantity", required=False, allow_null=True)
    standardUnit = serializers.CharField(source="standard_unit", required=False, allow_null=True, allow_blank=True)
    validated_model: CreateIngredientUnit

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        self.validated_model = validate_model(CreateIngredientUnit, data, ("body",))
        return self.validated_model.model_dump()


class UnitSerializer(UnitInputSerializer):
    id = serializers.UUIDField(read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True, allow_null=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True, allow_null=True)

    def to_representation(self, instance: IngredientUnit) -> dict[str, Any]:
        # Preserve Pydantic's timestamp/UUID rendering and full camelCase field set.
        return IngredientUnit.model_validate(instance).model_dump(mode="json", by_alias=True)


class UnitPaginationSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    per_page = serializers.IntegerField()
    total = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    items = UnitSerializer(many=True)
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)


class UnitMergeSerializer(serializers.Serializer):
    fromUnit = serializers.UUIDField(source="from_unit")
    toUnit = serializers.UUIDField(source="to_unit")
    validated_model: MergeUnit

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        self.validated_model = validate_model(MergeUnit, data, ("body",))
        return self.validated_model.model_dump()


class UnitPathSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()

    def to_internal_value(self, data: dict[str, Any]) -> dict[str, UUID]:
        try:
            return {"item_id": TypeAdapter(UUID4).validate_python(data["item_id"])}
        except ValidationError as exc:
            errors = [{**error, "loc": ("path", "item_id")} for error in exc.errors(include_url=False)]
            raise RequestValidationError(errors) from exc
