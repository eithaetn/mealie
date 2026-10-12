from pydantic import UUID4

from mealie.core.api_error import APIError
from mealie.core.security import hash_password
from mealie.core.security.providers.credentials_provider import CredentialsProvider
from mealie.db.models.users.users import AuthMethod
from mealie.lang import get_locale_provider
from mealie.lang.providers import Translator
from mealie.repos.all_repositories import AllRepositories
from mealie.schema.response import ErrorResponse, SuccessResponse
from mealie.schema.user import ChangePassword, PrivateUser, UserBase, UserOut
from mealie.schema.user.user import UserRatings, UserRatingSummary
from mealie.services._base_service import BaseService
from mealie.services.user_services.permissions import assert_user_change_allowed


class AccountService(BaseService):
    def __init__(self, repos: AllRepositories, user: PrivateUser, translator: Translator | None = None) -> None:
        super().__init__()
        self.repos = repos
        self.user = user
        self.translator = translator or get_locale_provider(None)

    def get_self(self) -> UserOut:
        return UserOut.model_validate(self.user.model_dump())

    def get_ratings(self, favorites_only: bool = False) -> UserRatings[UserRatingSummary]:
        return UserRatings[UserRatingSummary](
            ratings=self.repos.user_ratings.get_by_user(self.user.id, favorites_only=favorites_only)
        )

    def get_rating(self, recipe_id: UUID4) -> UserRatingSummary:
        rating = self.repos.user_ratings.get_by_user_and_recipe(self.user.id, recipe_id)
        if not rating:
            raise APIError(404, ErrorResponse.respond("User has not rated this recipe"))
        return UserRatingSummary.model_validate(rating.model_dump())

    def update_password(self, data: ChangePassword) -> dict:
        t = self.translator.t
        if self.user.auth_method == AuthMethod.LDAP:
            raise APIError(400, ErrorResponse.respond(t("user.ldap-update-password-unavailable")))
        if not CredentialsProvider.verify_password(data.current_password, self.user.password):
            raise APIError(400, ErrorResponse.respond(t("user.invalid-current-password")))
        self.user.password = hash_password(data.new_password)
        try:
            self.repos.users.update_password(self.user.id, self.user.password)
        except Exception as exc:
            raise APIError(400, ErrorResponse.respond("Failed to update password")) from exc
        return SuccessResponse.respond(t("user.password-updated"))

    def update_user(self, user_id: UUID4, data: UserBase) -> dict:
        assert_user_change_allowed(user_id, self.user, data)
        try:
            self.repos.users.update(user_id, data.model_dump())
        except Exception as exc:
            raise APIError(400, ErrorResponse.respond("Failed to update user")) from exc
        return SuccessResponse.respond(self.translator.t("user.user-updated"))
