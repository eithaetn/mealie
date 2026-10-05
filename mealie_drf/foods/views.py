from functools import cached_property

from rest_framework.request import Request
from rest_framework.response import Response

from mealie.core.exceptions import mealie_registered_exceptions
from mealie.core.root_logger import get_logger
from mealie.lang.providers import get_locale_provider
from mealie.repos.repository_foods import RepositoryFood
from mealie.routes._base.checks import OperationChecks
from mealie.routes._base.mixins import HttpRepo
from mealie.schema import mapper
from mealie.schema.recipe.recipe_ingredient import CreateIngredientFood, IngredientFood, SaveIngredientFood
from mealie.schema.response.pagination import PaginationQuery
from mealie.schema.response.responses import SuccessResponse
from mealie_drf.context import get_request_context
from mealie_drf.crud import CrudAPIView
from mealie_drf.errors import MealieAPIError
from mealie_drf.foods.serializers import (
    FoodInputSerializer,
    FoodMergeSerializer,
    FoodPaginationSerializer,
    FoodSerializer,
)
from mealie_drf.units.serializers import validate_model


class FoodAPIView(CrudAPIView):
    """Reuse the established JSON, locale, UUID and HTTP compatibility boundary."""

    @cached_property
    def repo(self) -> RepositoryFood:
        return get_request_context(self.request).repos.ingredient_foods

    @cached_property
    def crud(self) -> HttpRepo[SaveIngredientFood, IngredientFood, CreateIngredientFood]:
        translator = get_locale_provider(self.request.headers.get("Accept-Language"))

        def message(error: type[Exception]) -> str:
            return mealie_registered_exceptions(translator).get(error, translator.t("generic.server-error"))

        return HttpRepo(self.repo, get_logger(), message)

    def can_organize(self) -> None:
        OperationChecks(get_request_context(self.request).user).can_organize()

    def food_response(self, food: IngredientFood | None, status: int = 200) -> Response:
        response = Response(FoodSerializer(food).data if food is not None else None, status=status)
        if food is not None and (updated_at := response.data.get("updatedAt")):
            response["last-modified"] = updated_at
            response["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


class FoodListView(FoodAPIView):
    http_method_names = ["get", "post"]

    def get(self, request: Request) -> Response:
        query = {
            field.alias or name: request.query_params[field.alias or name]
            for name, field in PaginationQuery.model_fields.items()
            if (field.alias or name) in request.query_params
        }
        pagination = validate_model(PaginationQuery, query, ("query",))
        result = self.repo.page_all(pagination, override=IngredientFood, search=request.query_params.get("search"))
        result.set_pagination_guides("/foods", pagination.model_dump())
        return Response(FoodPaginationSerializer(result).data)

    def post(self, request: Request) -> Response:
        serializer = FoodInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.can_organize()
        data = mapper.cast(
            serializer.validated_model, SaveIngredientFood, group_id=get_request_context(request).group_id
        )
        return self.food_response(self.crud.create_one(data), status=201)


class FoodDetailView(FoodAPIView):
    http_method_names = ["get", "put", "delete"]

    def get(self, request: Request, item_id: str) -> Response:
        return self.food_response(self.crud.get_one(self.validated_id(item_id)))

    def put(self, request: Request, item_id: str) -> Response:
        food_id = self.validated_id(item_id)
        serializer = FoodInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.can_organize()
        data = mapper.cast(
            serializer.validated_model, SaveIngredientFood, group_id=get_request_context(request).group_id
        )
        return self.food_response(self.crud.update_one(data, food_id))

    def delete(self, request: Request, item_id: str) -> Response:
        food_id = self.validated_id(item_id)
        self.can_organize()
        return self.food_response(self.crud.delete_one(food_id))


class FoodMergeView(FoodDetailView):
    def put(self, request: Request, item_id: str = "merge") -> Response:
        serializer = FoodMergeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.can_organize()
        data = serializer.validated_model
        try:
            self.repo.merge(data.from_food, data.to_food)
        except Exception as exc:
            get_logger().error(exc)
            raise MealieAPIError(500, "Failed to merge foods") from exc
        return Response(SuccessResponse.respond("Successfully merged foods"))
