from typing import Any

from rest_framework import serializers

from mealie.schema.recipe.recipe_ingredient import CreateIngredientFood, IngredientFood, MergeFood
from mealie_drf.units.serializers import UnitAliasSerializer, validate_model


class FoodSubstitutionSerializer(serializers.Serializer):
    substituteFoodId = serializers.UUIDField(source="substitute_food_id", required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    substituteFood = serializers.JSONField(source="substitute_food", read_only=True)


class FoodInputSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False, allow_null=True)
    name = serializers.CharField(allow_blank=True, trim_whitespace=False)
    pluralName = serializers.CharField(source="plural_name", required=False, allow_null=True, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    extras = serializers.JSONField(required=False, allow_null=True)
    labelId = serializers.UUIDField(source="label_id", required=False, allow_null=True)
    aliases = UnitAliasSerializer(many=True, required=False)
    substitutions = FoodSubstitutionSerializer(many=True, required=False)
    householdsWithIngredientFood = serializers.ListField(
        source="households_with_ingredient_food", child=serializers.CharField(), required=False
    )
    validated_model: CreateIngredientFood

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        self.validated_model = validate_model(CreateIngredientFood, data, ("body",))
        return self.validated_model.model_dump()


class FoodSerializer(FoodInputSerializer):
    id = serializers.UUIDField(read_only=True)
    label = serializers.JSONField(read_only=True, allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True, allow_null=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True, allow_null=True)

    def to_representation(self, instance: IngredientFood) -> dict[str, Any]:
        return IngredientFood.model_validate(instance).model_dump(mode="json", by_alias=True)


class FoodPaginationSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    per_page = serializers.IntegerField()
    total = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    items = FoodSerializer(many=True)
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)


class FoodMergeSerializer(serializers.Serializer):
    fromFood = serializers.UUIDField(source="from_food")
    toFood = serializers.UUIDField(source="to_food")
    validated_model: MergeFood

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        self.validated_model = validate_model(MergeFood, data, ("body",))
        return self.validated_model.model_dump()
