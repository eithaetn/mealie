from typing import Any

from pydantic import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from mealie.drf.base import UserAPIView
from mealie.drf.pagination import pagination_query
from mealie.repos.all_repositories import get_repositories
from mealie.schema.household.household_permissions import SetPermissions
from mealie.schema.household.household_preferences import UpdateHouseholdPreferences
from mealie.services.household_services.household_self_service import HouseholdSelfService


class HouseholdAPIView(UserAPIView):
    def household_service(self, request: Request) -> HouseholdSelfService:
        repos = get_repositories(self.db, group_id=request.user.group_id, household_id=request.user.household_id)
        return HouseholdSelfService(repos, request.user)


class HouseholdSelfView(HouseholdAPIView):
    http_method_names = ["get"]

    def get(self, request: Request) -> Response:
        result = self.household_service(request).get_household()
        return Response(result.model_dump(mode="json", by_alias=True))


class HouseholdRecipeView(HouseholdAPIView):
    http_method_names = ["get"]

    def get(self, request: Request, recipe_slug: str) -> Response:
        result = self.household_service(request).get_recipe(recipe_slug)
        return Response(result.model_dump(mode="json", by_alias=True))


class HouseholdMembersView(HouseholdAPIView):
    http_method_names = ["get"]

    def get(self, request: Request) -> Response:
        result = self.household_service(request).get_members(pagination_query(request))
        return Response(result.model_dump(mode="json", by_alias=True))


class HouseholdPreferencesView(HouseholdAPIView):
    http_method_names = ["get", "put"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        if request.method == "PUT":
            self.body_schema = UpdateHouseholdPreferences
        super().initial(request, *args, **kwargs)

    def get(self, request: Request) -> Response:
        result = self.household_service(request).get_preferences()
        return Response(result.model_dump(mode="json", by_alias=True))

    def put(self, request: Request) -> Response:
        try:
            data = self.validated_body(UpdateHouseholdPreferences)
        except ValidationError as exc:
            return self.validation_error(exc)
        result = self.household_service(request).update_preferences(data)
        return Response(result.model_dump(mode="json", by_alias=True))


class HouseholdPermissionsView(HouseholdAPIView):
    http_method_names = ["put"]
    body_schema = SetPermissions

    def put(self, request: Request) -> Response:
        try:
            data = self.validated_body(SetPermissions)
        except ValidationError as exc:
            return self.validation_error(exc)
        result = self.household_service(request).set_permissions(data)
        return Response(result.model_dump(mode="json", by_alias=True))


class HouseholdStatisticsView(HouseholdAPIView):
    http_method_names = ["get"]

    def get(self, request: Request) -> Response:
        result = self.household_service(request).get_statistics()
        return Response(result.model_dump(mode="json", by_alias=True))
