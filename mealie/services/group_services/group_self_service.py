from typing import cast
from uuid import UUID

from mealie.core.api_error import APIError
from mealie.repos.all_repositories import AllRepositories
from mealie.schema.group.group_preferences import ReadGroupPreferences, UpdateGroupPreferences
from mealie.schema.group.group_statistics import GroupStorage
from mealie.schema.household.household import HouseholdSummary
from mealie.schema.response.pagination import PaginationBase, PaginationQuery
from mealie.schema.user.user import GroupSummary, PrivateUser, UserSummary
from mealie.services._base_service import BaseService
from mealie.services.group_services.group_service import GroupService


class GroupSelfService(BaseService):
    def __init__(self, repos: AllRepositories, user: PrivateUser) -> None:
        super().__init__()
        self.repos = repos
        self.user = user

    def get_group(self) -> GroupSummary:
        return self.repos.groups.get_one(self.user.group_id).cast(GroupSummary)

    def get_preferences(self) -> ReadGroupPreferences:
        return self.repos.groups.get_one(self.user.group_id).preferences

    def update_preferences(self, data: UpdateGroupPreferences) -> ReadGroupPreferences:
        # Use the effective permission supplied by the existing user model.
        if not self.user.can_manage:
            raise APIError(403, "Forbidden")
        return self.repos.group_preferences.update(self.user.group_id, data)

    def get_storage(self) -> GroupStorage:
        return GroupService(self.user.group_id, self.repos).calculate_group_storage()

    def get_members(self, query: PaginationQuery) -> PaginationBase[UserSummary]:
        response = cast(PaginationBase[UserSummary], self.repos.users.page_all(query, override=UserSummary))
        response.set_pagination_guides("/groups/members", query.model_dump())
        return response

    def get_member(self, username_or_id: str) -> UserSummary:
        try:
            UUID(username_or_id)
            key = "id"
        except ValueError:
            key = "username"
        member = self.repos.users.get_one(username_or_id, key)
        if not member:
            raise APIError(404, "User Not Found")
        return member.cast(UserSummary)

    def get_households(self, query: PaginationQuery) -> PaginationBase[HouseholdSummary]:
        response = cast(
            PaginationBase[HouseholdSummary], self.repos.households.page_all(query, override=HouseholdSummary)
        )
        response.set_pagination_guides("/groups/households", query.model_dump())
        return response

    def get_household(self, slug_or_id: str) -> HouseholdSummary:
        household = self.repos.households.get_by_slug_or_id(slug_or_id)
        if not household:
            raise APIError(404, "Household not found")
        return household.cast(HouseholdSummary)
