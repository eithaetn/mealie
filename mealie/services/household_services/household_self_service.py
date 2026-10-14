from typing import cast

from mealie.core.api_error import APIError
from mealie.repos.all_repositories import AllRepositories
from mealie.schema.household import HouseholdInDB, HouseholdRecipeSummary
from mealie.schema.household.household_permissions import SetPermissions
from mealie.schema.household.household_preferences import ReadHouseholdPreferences, UpdateHouseholdPreferences
from mealie.schema.household.household_statistics import HouseholdStatistics
from mealie.schema.response.pagination import PaginationBase, PaginationQuery
from mealie.schema.user.user import PrivateUser, UserOut
from mealie.services._base_service import BaseService
from mealie.services.household_services.household_service import HouseholdService
from mealie.services.query_filter.builder import QueryFilterBuilder


class HouseholdSelfService(BaseService):
    def __init__(self, repos: AllRepositories, user: PrivateUser) -> None:
        super().__init__()
        self.repos = repos
        self.user = user
        self.service = HouseholdService(user.group_id, user.household_id, repos)

    def get_household(self) -> HouseholdInDB:
        return self.repos.households.get_one(self.user.household_id)

    def get_recipe(self, slug: str) -> HouseholdRecipeSummary:
        result = self.service.get_household_recipe(slug)
        if result is None:
            raise APIError(404, "Recipe not found")
        return result

    def get_members(self, query: PaginationQuery) -> PaginationBase[UserOut]:
        if not self.user.can_manage:
            raise APIError(403, "Forbidden")
        query.query_filter = QueryFilterBuilder.combine_filters(
            query.query_filter, f"household_id={self.user.household_id}"
        )
        result = cast(PaginationBase[UserOut], self.repos.users.page_all(query, override=UserOut))
        result.set_pagination_guides("/households/members", query.model_dump())
        return result

    def get_preferences(self) -> ReadHouseholdPreferences:
        return self.get_household().preferences

    def update_preferences(self, data: UpdateHouseholdPreferences) -> ReadHouseholdPreferences:
        if not self.user.can_manage_household:
            raise APIError(403, "Forbidden")
        return self.repos.household_preferences.update(self.user.household_id, data)

    def set_permissions(self, data: SetPermissions) -> UserOut:
        if not self.user.can_manage:
            raise APIError(403, "Forbidden")
        target = self.repos.users.get_one(data.user_id)
        if target is None:
            raise APIError(404, "User not found")
        if target.group_id != self.user.group_id:
            raise APIError(403, "User is not a member of this group")
        if target.household_id != self.user.household_id:
            raise APIError(403, "User is not a member of this household")
        if target.id == self.user.id:
            raise APIError(403, "User is not allowed to change their own permissions")
        target.can_invite = data.can_invite
        target.can_manage = data.can_manage
        target.can_manage_household = data.can_manage_household
        target.can_organize = data.can_organize
        return self.repos.users.update(data.user_id, target).cast(UserOut)

    def get_statistics(self) -> HouseholdStatistics:
        return self.service.calculate_statistics()
