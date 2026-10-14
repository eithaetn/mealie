from uuid import UUID

from pydantic import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from mealie.drf.base import UserAPIView
from mealie.repos.all_repositories import get_repositories
from mealie.schema.user.user import UserRatingUpdate
from mealie.services.user_services.recipe_rating_service import RecipeRatingService


class UserRecipeView(UserAPIView):
    def rating_service(self, request: Request) -> RecipeRatingService:
        repos = get_repositories(self.db, group_id=request.user.group_id, household_id=request.user.household_id)
        return RecipeRatingService(repos, request.user)


class RatingsView(UserRecipeView):
    http_method_names = ["get"]
    favorites_only = False

    def get(self, request: Request, id: UUID) -> Response:
        result = self.rating_service(request).list_ratings(self.validated_id(id), self.favorites_only)
        return Response(result.model_dump(mode="json", by_alias=True))


class FavoritesView(RatingsView):
    favorites_only = True


class RatingView(UserRecipeView):
    http_method_names = ["post"]
    body_schema = UserRatingUpdate

    def post(self, request: Request, id: UUID, slug: str) -> Response:
        user_id = self.validated_id(id)
        try:
            data = self.validated_body(UserRatingUpdate)
        except ValidationError as exc:
            return self.validation_error(exc)
        self.rating_service(request).set_rating(user_id, slug, data)
        return Response(None)


class FavoriteView(UserRecipeView):
    http_method_names = ["post", "delete"]

    def post(self, request: Request, id: UUID, slug: str) -> Response:
        self.rating_service(request).set_rating(self.validated_id(id), slug, UserRatingUpdate(is_favorite=True))
        return Response(None)

    def delete(self, request: Request, id: UUID, slug: str) -> Response:
        self.rating_service(request).set_rating(self.validated_id(id), slug, UserRatingUpdate(is_favorite=False))
        return Response(None)
