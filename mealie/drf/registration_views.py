from pydantic import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from mealie.core.root_logger import get_logger
from mealie.drf.base import SessionAPIView
from mealie.lang import get_locale_provider
from mealie.repos.all_repositories import get_repositories
from mealie.schema.user.registration import CreateUserRegistration
from mealie.schema.user.user_passwords import ForgotPassword, ResetPassword
from mealie.services.event_bus_service.event_bus_service import EventBusService
from mealie.services.user_services.password_reset_service import PasswordResetService
from mealie.services.user_services.registration_service import RegistrationService


class RegistrationView(SessionAPIView):
    authentication_classes: list = []
    permission_classes: list = []
    http_method_names = ["post"]
    body_schema = CreateUserRegistration

    def post(self, request: Request) -> Response:
        try:
            data = self.validated_body(CreateUserRegistration)
        except ValidationError as exc:
            return self.validation_error(exc)
        translator = get_locale_provider(request.headers.get("accept-language"))
        repos = get_repositories(self.db, group_id=None, household_id=None)
        event_bus = EventBusService(request._request.scope["mealie.background_tasks"], self.db, translator)
        user = RegistrationService(get_logger(), repos, translator).register_public_user(data, event_bus)
        return Response(user.model_dump(mode="json", by_alias=True), status=201)


class ForgotPasswordView(SessionAPIView):
    authentication_classes: list = []
    permission_classes: list = []
    http_method_names = ["post"]
    body_schema = ForgotPassword

    def post(self, request: Request) -> Response:
        try:
            data = self.validated_body(ForgotPassword)
        except ValidationError as exc:
            return self.validation_error(exc)
        result = PasswordResetService(self.db).send_reset_email(data.email, request.headers.get("accept-language"))
        return Response(result)


class ResetPasswordView(SessionAPIView):
    authentication_classes: list = []
    permission_classes: list = []
    http_method_names = ["post"]
    body_schema = ResetPassword

    def post(self, request: Request) -> Response:
        try:
            data = self.validated_body(ResetPassword)
        except ValidationError as exc:
            return self.validation_error(exc)
        return Response(PasswordResetService(self.db).reset_password(data.token, data.password))
