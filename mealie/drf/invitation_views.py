from typing import Any

from pydantic import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from mealie.drf.base import UserAPIView
from mealie.repos.all_repositories import get_repositories
from mealie.schema.household.invite_token import CreateInviteToken, EmailInvitation
from mealie.services.household_services.invitation_service import InvitationService


class InvitationAPIView(UserAPIView):
    def invitation_service(self, request: Request) -> InvitationService:
        repos = get_repositories(self.db, group_id=request.user.group_id, household_id=request.user.household_id)
        return InvitationService(repos, request.user)


class InvitationsView(InvitationAPIView):
    http_method_names = ["get", "post"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        if request.method == "POST":
            self.body_schema = CreateInviteToken
        super().initial(request, *args, **kwargs)

    def get(self, request: Request) -> Response:
        result = self.invitation_service(request).list_tokens()
        return Response([item.model_dump(mode="json", by_alias=True) for item in result])

    def post(self, request: Request) -> Response:
        try:
            data = self.validated_body(CreateInviteToken)
        except ValidationError as exc:
            return self.validation_error(exc)
        result = self.invitation_service(request).create(data)
        return Response(result.model_dump(mode="json", by_alias=True), status=201)


class InvitationEmailView(InvitationAPIView):
    http_method_names = ["post"]
    body_schema = EmailInvitation

    def post(self, request: Request) -> Response:
        try:
            data = self.validated_body(EmailInvitation)
        except ValidationError as exc:
            return self.validation_error(exc)
        result = self.invitation_service(request).email(data, request.headers.get("accept-language"))
        return Response(result.model_dump(mode="json", by_alias=True))
