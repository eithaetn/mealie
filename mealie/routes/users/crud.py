from typing import Any

from fastapi import HTTPException
from pydantic import UUID4

from mealie.core.api_error import APIError
from mealie.routes._base import BaseUserController, controller
from mealie.routes._base.routers import UserAPIRouter
from mealie.schema.user import ChangePassword, UserBase, UserOut
from mealie.schema.user.user import UserRatings, UserRatingSummary
from mealie.services.user_services.account_service import AccountService

user_router = UserAPIRouter(prefix="/users", tags=["Users: CRUD"])


@controller(user_router)
class UserController(BaseUserController):
    def _account_call(self, operation: str, *args: Any) -> Any:
        try:
            return getattr(AccountService(self.repos, self.user, self.translator), operation)(*args)
        except APIError as exc:
            raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc

    @user_router.get("/self", response_model=UserOut)
    def get_logged_in_user(self) -> UserOut:
        return self._account_call("get_self")

    @user_router.get("/self/ratings", response_model=UserRatings[UserRatingSummary])
    def get_logged_in_user_ratings(self) -> UserRatings[UserRatingSummary]:
        return self._account_call("get_ratings")

    @user_router.get("/self/ratings/{recipe_id}", response_model=UserRatingSummary)
    def get_logged_in_user_rating_for_recipe(self, recipe_id: UUID4) -> UserRatingSummary:
        return self._account_call("get_rating", recipe_id)

    @user_router.get("/self/favorites", response_model=UserRatings[UserRatingSummary])
    def get_logged_in_user_favorites(self) -> UserRatings[UserRatingSummary]:
        return self._account_call("get_ratings", True)

    @user_router.put("/password", response_model=None)
    def update_password(self, password_change: ChangePassword) -> dict:
        return self._account_call("update_password", password_change)

    @user_router.put("/{item_id}", response_model=None)
    def update_user(self, item_id: UUID4, new_data: UserBase) -> dict:
        return self._account_call("update_user", item_id, new_data)
