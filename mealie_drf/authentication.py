import asyncio

from fastapi.security.utils import get_authorization_scheme_param
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from mealie.core.dependencies.dependencies import get_current_user
from mealie.schema.user import PrivateUser
from mealie_drf.context import MealieRequestContext, get_request_session


class MealieTokenAuthentication(BaseAuthentication):
    """Reuse Mealie's token validation in synchronous DRF views, without Django users."""

    def authenticate(self, request: Request) -> tuple[PrivateUser, str]:
        scheme, credentials = get_authorization_scheme_param(request.headers.get("Authorization"))
        # Match OAuth2PasswordBearer(auto_error=False) and get_auth_token: a Bearer
        # header takes precedence, including an empty one; other schemes permit cookie fallback.
        token = credentials if scheme.lower() == "bearer" else request.COOKIES.get("mealie.access_token", "")
        session = get_request_session(request)
        # get_current_user is async but performs synchronous SQLAlchemy work. Running
        # it here keeps that work on the sync view's thread with its request session.
        user = asyncio.run(get_current_user(token=token, session=session))
        request.mealie_context = MealieRequestContext(user=user, session=session)
        return user, token

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"
