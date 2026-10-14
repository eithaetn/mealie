from uuid import UUID

from fastapi.exceptions import RequestValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from starlette.datastructures import UploadFile

from mealie.drf.base import UserAPIView
from mealie.repos.all_repositories import get_repositories
from mealie.services.user_services.profile_image_service import ProfileImageService


class ProfileImageView(UserAPIView):
    http_method_names = ["post"]
    form_body = True

    def post(self, request: Request, id: UUID) -> Response:
        user_id = self.validated_id(id)
        profile = (self.parsed_form or {}).get("profile")
        if profile is None or profile == "":
            raise RequestValidationError(
                [{"type": "missing", "loc": ("body", "profile"), "msg": "Field required", "input": None}]
            )
        if not isinstance(profile, UploadFile):
            error = ValueError(f"Expected UploadFile, received: {type(profile)}")
            raise RequestValidationError(
                [
                    {
                        "type": "value_error",
                        "loc": ("body", "profile"),
                        "msg": f"Value error, {error}",
                        "input": profile,
                        "ctx": {"error": error},
                    }
                ]
            )
        repos = get_repositories(self.db, group_id=request.user.group_id, household_id=request.user.household_id)
        ProfileImageService(repos, request.user).update(user_id, profile.file)
        return Response(None)
