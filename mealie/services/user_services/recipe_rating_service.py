from uuid import UUID

from pydantic import UUID4

from mealie.core.api_error import APIError
from mealie.repos.all_repositories import AllRepositories, get_repositories
from mealie.schema.recipe import Recipe
from mealie.schema.response.responses import ErrorResponse
from mealie.schema.user.user import PrivateUser, UserRatingCreate, UserRatingOut, UserRatings, UserRatingUpdate
from mealie.services._base_service import BaseService
from mealie.services.user_services.permissions import assert_user_change_allowed


class RecipeRatingService(BaseService):
    def __init__(self, repos: AllRepositories, user: PrivateUser) -> None:
        super().__init__()
        self.repos = repos
        self.user = user

    def list_ratings(self, user_id: UUID4, favorites_only: bool = False) -> UserRatings[UserRatingOut]:
        assert_user_change_allowed(user_id, self.user, self.user)
        return UserRatings[UserRatingOut](
            ratings=self.repos.user_ratings.get_by_user(user_id, favorites_only=favorites_only)
        )

    def get_recipe(self, slug_or_id: str | UUID) -> Recipe:
        recipes = get_repositories(self.repos.session, group_id=self.user.group_id, household_id=None).recipes
        if isinstance(slug_or_id, str):
            try:
                slug_or_id = UUID(slug_or_id)
            except ValueError:
                pass
        key = "id" if isinstance(slug_or_id, UUID) else "slug"
        recipe = recipes.get_one(slug_or_id, key=key)
        if not recipe:
            raise APIError(404, ErrorResponse.respond(message="Not found."))
        return recipe

    def set_rating(self, user_id: UUID4, slug: str, data: UserRatingUpdate) -> None:
        assert_user_change_allowed(user_id, self.user, self.user)
        recipe = self.get_recipe(slug)
        rating = self.repos.user_ratings.get_by_user_and_recipe(user_id, recipe.id)
        if not rating:
            self.repos.user_ratings.create(
                UserRatingCreate(
                    user_id=user_id, recipe_id=recipe.id, rating=data.rating, is_favorite=data.is_favorite or False
                )
            )
        else:
            if data.rating is not None:
                rating.rating = data.rating
            if data.is_favorite is not None:
                rating.is_favorite = data.is_favorite
            self.repos.user_ratings.update(rating.id, rating)
