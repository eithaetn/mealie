from typing import Any

from pydantic import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from mealie.drf.base import UserAPIView
from mealie.drf.pagination import pagination_query
from mealie.repos.all_repositories import get_repositories
from mealie.schema.group.group_preferences import UpdateGroupPreferences
from mealie.services.group_services.group_self_service import GroupSelfService


class GroupAPIView(UserAPIView):
    def group_service(self, request: Request) -> GroupSelfService:
        repos = get_repositories(self.db, group_id=request.user.group_id, household_id=request.user.household_id)
        return GroupSelfService(repos, request.user)


class GroupSelfView(GroupAPIView):
    http_method_names = ["get"]

    def get(self, request: Request) -> Response:
        result = self.group_service(request).get_group()
        return Response(result.model_dump(mode="json", by_alias=True))


class GroupPreferencesView(GroupAPIView):
    http_method_names = ["get", "put"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        if request.method == "PUT":
            self.body_schema = UpdateGroupPreferences
        super().initial(request, *args, **kwargs)

    def get(self, request: Request) -> Response:
        result = self.group_service(request).get_preferences()
        return Response(result.model_dump(mode="json", by_alias=True))

    def put(self, request: Request) -> Response:
        try:
            data = self.validated_body(UpdateGroupPreferences)
        except ValidationError as exc:
            return self.validation_error(exc)
        result = self.group_service(request).update_preferences(data)
        return Response(result.model_dump(mode="json", by_alias=True))


class GroupStorageView(GroupAPIView):
    http_method_names = ["get"]

    def get(self, request: Request) -> Response:
        result = self.group_service(request).get_storage()
        return Response(result.model_dump(mode="json", by_alias=True))


class GroupMembersView(GroupAPIView):
    http_method_names = ["get"]

    def get(self, request: Request) -> Response:
        result = self.group_service(request).get_members(pagination_query(request))
        return Response(result.model_dump(mode="json", by_alias=True))


class GroupMemberView(GroupAPIView):
    http_method_names = ["get"]

    def get(self, request: Request, username_or_id: str) -> Response:
        result = self.group_service(request).get_member(username_or_id)
        return Response(result.model_dump(mode="json", by_alias=True))


class GroupHouseholdsView(GroupAPIView):
    http_method_names = ["get"]

    def get(self, request: Request) -> Response:
        result = self.group_service(request).get_households(pagination_query(request))
        return Response(result.model_dump(mode="json", by_alias=True))


class GroupHouseholdView(GroupAPIView):
    http_method_names = ["get"]

    def get(self, request: Request, household_slug: str) -> Response:
        result = self.group_service(request).get_household(household_slug)
        return Response(result.model_dump(mode="json", by_alias=True))
