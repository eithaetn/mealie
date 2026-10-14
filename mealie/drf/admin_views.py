from rest_framework.request import Request
from rest_framework.response import Response

from mealie.drf.authentication import MealieAdminPermission
from mealie.drf.base import UserAPIView
from mealie.repos.all_repositories import get_repositories
from mealie.services.admin_about_service import AdminAboutService


class AdminAboutView(UserAPIView):
    permission_classes = [MealieAdminPermission]
    http_method_names = ["get"]
    operation = "get_info"

    def get(self, request: Request) -> Response:
        # Global repositories are only constructed after the admin permission check.
        repos = get_repositories(self.db, group_id=None, household_id=None)
        result = getattr(AdminAboutService(repos), self.operation)()
        return Response(result.model_dump(mode="json", by_alias=True))


class AdminStatisticsView(AdminAboutView):
    operation = "get_statistics"


class AdminConfigView(AdminAboutView):
    operation = "check_config"
