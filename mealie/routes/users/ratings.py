from typing import Any

from fastapi import HTTPException
from pydantic import UUID4

from mealie.core.api_error import APIError
from mealie.routes._base import BaseUserController, controller
from mealie.routes._base.routers import UserAPIRouter
from mealie.schema.user.user import UserRatingOut, UserRatings, UserRatingUpdate
from mealie.services.user_services.recipe_rating_service import RecipeRatingService

router = UserAPIRouter()


@controller(router)
class UserRatingsController(BaseUserController):
    def _rating_call(self, operation: str, *args: Any) -> Any:
        try:
            return getattr(RecipeRatingService(self.repos, self.user), operation)(*args)
        except APIError as exc:
            raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc

    @router.get("/{id}/ratings", response_model=UserRatings[UserRatingOut])
    async def get_ratings(self, id: UUID4) -> UserRatings[UserRatingOut]:
        return self._rating_call("list_ratings", id)

    @router.get("/{id}/favorites", response_model=UserRatings[UserRatingOut])
    async def get_favorites(self, id: UUID4) -> UserRatings[UserRatingOut]:
        return self._rating_call("list_ratings", id, True)

    @router.post("/{id}/ratings/{slug}", response_model=None)
    def set_rating(self, id: UUID4, slug: str, data: UserRatingUpdate) -> None:
        self._rating_call("set_rating", id, slug, data)

    @router.post("/{id}/favorites/{slug}", response_model=None)
    def add_favorite(self, id: UUID4, slug: str) -> None:
        self.set_rating(id, slug, UserRatingUpdate(is_favorite=True))

    @router.delete("/{id}/favorites/{slug}", response_model=None)
    def remove_favorite(self, id: UUID4, slug: str) -> None:
        self.set_rating(id, slug, UserRatingUpdate(is_favorite=False))
