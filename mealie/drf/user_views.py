from uuid import UUID

from pydantic import UUID4, TypeAdapter, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from mealie.drf.base import UserAPIView
from mealie.lang import get_locale_provider
from mealie.repos.all_repositories import get_repositories
from mealie.schema.user import ChangePassword, LongLiveTokenIn, UserBase
from mealie.services.api_token_service import ApiTokenService
from mealie.services.user_services.account_service import AccountService


class UserAccountView(UserAPIView):
    def account_service(self, request: Request) -> AccountService:
        repos = get_repositories(self.db, group_id=request.user.group_id, household_id=request.user.household_id)
        return AccountService(repos, request.user, get_locale_provider(request.headers.get("accept-language")))


class UserSelfView(UserAccountView):
    http_method_names = ["get"]

    def get(self, request: Request) -> Response:
        # Construct the public response schema to exclude credentials/private fields.
        result = self.account_service(request).get_self()
        return Response(result.model_dump(mode="json", by_alias=True))


class ApiTokenCreateView(UserAPIView):
    http_method_names = ["post"]
    body_schema = LongLiveTokenIn

    def post(self, request: Request) -> Response:
        try:
            data = self.validated_body(LongLiveTokenIn)
        except ValidationError as exc:
            return self.validation_error(exc)
        repos = get_repositories(self.db, group_id=request.user.group_id, household_id=request.user.household_id)
        result = ApiTokenService(repos, request.user).create(data)
        return Response(result.model_dump(mode="json", by_alias=True), status=201)


class ApiTokenDeleteView(UserAPIView):
    http_method_names = ["delete"]

    def delete(self, request: Request, token_id: str) -> Response:
        try:
            parsed_id = TypeAdapter(int).validate_python(token_id)
        except ValidationError as exc:
            return self.validation_error(exc, "path", "token_id")
        repos = get_repositories(self.db, group_id=request.user.group_id, household_id=request.user.household_id)
        result = ApiTokenService(repos, request.user).delete(parsed_id)
        return Response(result.model_dump(mode="json", by_alias=True))


class UserRatingsView(UserAccountView):
    http_method_names = ["get"]
    favorites_only = False

    def get(self, request: Request) -> Response:
        result = self.account_service(request).get_ratings(self.favorites_only)
        return Response(result.model_dump(mode="json", by_alias=True))


class UserFavoritesView(UserRatingsView):
    favorites_only = True


class UserRatingView(UserAccountView):
    http_method_names = ["get"]

    def get(self, request: Request, recipe_id: UUID) -> Response:
        try:
            validated_id = TypeAdapter(UUID4).validate_python(str(recipe_id))
        except ValidationError as exc:
            return self.validation_error(exc, "path", "recipe_id")
        result = self.account_service(request).get_rating(validated_id)
        return Response(result.model_dump(mode="json", by_alias=True))


class UserPasswordView(UserAccountView):
    http_method_names = ["put"]
    body_schema = ChangePassword

    def put(self, request: Request) -> Response:
        try:
            data = self.validated_body(ChangePassword)
        except ValidationError as exc:
            return self.validation_error(exc)
        return Response(self.account_service(request).update_password(data))


class UserUpdateView(UserAccountView):
    http_method_names = ["put"]
    body_schema = UserBase

    def put(self, request: Request, item_id: UUID) -> Response:
        try:
            validated_id = TypeAdapter(UUID4).validate_python(str(item_id))
        except ValidationError as exc:
            return self.validation_error(exc, "path", "item_id")
        try:
            data = self.validated_body(UserBase)
        except ValidationError as exc:
            return self.validation_error(exc)
        return Response(self.account_service(request).update_user(validated_id, data))
