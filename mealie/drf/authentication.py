from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from mealie.core.security.authentication import AuthenticationError, TokenVerifier, extract_token
from mealie.schema.user import PrivateUser


class MealieAuthentication(BaseAuthentication):
    def authenticate(self, request: Request) -> tuple[PrivateUser, str]:
        token = extract_token(request.headers.get("Authorization"), request.COOKIES.get("mealie.access_token"))
        view = request.parser_context["view"]
        return TokenVerifier(view.db).resolve(token), token

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"


class MealieUserPermission(BasePermission):
    def has_permission(self, request: Request, view: object) -> bool:
        return isinstance(request.user, PrivateUser)


class MealieAdminPermission(MealieUserPermission):
    def has_permission(self, request: Request, view: object) -> bool:
        if not super().has_permission(request, view) or not request.user.admin:
            raise AuthenticationError(403, "Forbidden")
        return True
