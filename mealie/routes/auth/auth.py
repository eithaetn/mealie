from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.exceptions import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm.session import Session

from mealie.core import root_logger
from mealie.core.api_error import APIError
from mealie.core.config import get_app_settings
from mealie.core.dependencies import get_auth_token, get_current_user
from mealie.core.security.authentication import AuthenticationError, SessionAuthenticationService
from mealie.core.security.session_cookies import (
    SESSION_COOKIE_NAME,
    request_is_https,  # noqa: F401 - retained public helper
    session_cookie_attrs,
    set_session_cookie,
)
from mealie.db.db_setup import generate_session
from mealie.lang import get_locale_provider
from mealie.routes._base.routers import UserAPIRouter
from mealie.schema.user import PrivateUser
from mealie.schema.user.auth import CredentialsRequest, CredentialsRequestForm, NativeOIDCTokenRequest, OIDCNativeConfig
from mealie.services.oidc_service import OIDCService

public_router = APIRouter(tags=["Users: Authentication"])
user_router = UserAPIRouter(tags=["Users: Authentication"])
logger = root_logger.get_logger("auth")


settings = get_app_settings()


class MealieAuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    """seconds until the token expires, so clients can refresh before it does"""

    @classmethod
    def respond(cls, token: str, expires_in: timedelta, token_type: str = "bearer") -> dict:
        return cls(
            access_token=token,
            token_type=token_type,
            expires_in=int(expires_in.total_seconds()),
        ).model_dump()


@public_router.post("/token")
def get_token(
    request: Request,
    response: Response,
    data: CredentialsRequestForm = Depends(),
    session: Session = Depends(generate_session),
):
    if "x-forwarded-for" in request.headers:
        ip = request.headers["x-forwarded-for"]
        if "," in ip:  # if there are multiple IPs, the first one is canonically the true client
            ip = str(ip.split(",")[0])
    else:
        # request.client should never be null, except sometimes during testing
        ip = request.client.host if request.client else "unknown"

    try:
        access_token, duration = SessionAuthenticationService(session).login(CredentialsRequest(**data.__dict__), ip)
    except AuthenticationError as exc:
        raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc
    set_session_cookie(response, request, access_token, duration, data.remember_me)
    return MealieAuthToken.respond(access_token, duration)


@public_router.get("/oauth")
async def oauth_login(request: Request):
    try:
        return await OIDCService().login(request)
    except APIError as exc:
        raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc


@public_router.get("/oauth/callback")
async def oauth_callback(request: Request, response: Response, session: Session = Depends(generate_session)):
    try:
        token, duration = await OIDCService(session).callback(request)
    except APIError as exc:
        raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc
    set_session_cookie(response, request, token, duration, settings.OIDC_REMEMBER_ME)
    return MealieAuthToken.respond(token, duration)


@public_router.get("/oauth/native/config", response_model=OIDCNativeConfig)
async def oauth_native_config():
    try:
        return await OIDCService().native_config()
    except APIError as exc:
        raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc


@public_router.post("/oauth/native/token")
async def oauth_native_token(
    request: Request,
    response: Response,
    data: NativeOIDCTokenRequest,
    session: Session = Depends(generate_session),
):
    try:
        token, duration = await OIDCService(session).native_token(data)
    except APIError as exc:
        raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc
    set_session_cookie(response, request, token, duration, settings.OIDC_REMEMBER_ME)
    return MealieAuthToken.respond(token, duration)


@user_router.post("/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    current_user: PrivateUser = Depends(get_current_user),
    token: str = Depends(get_auth_token),
):
    """Exchange a valid session token for a fresh one.

    The new token carries over the remember-me choice recorded on the old one, so refreshing doesn't
    downgrade a remembered session to one that dies with the browser.
    """
    try:
        access_token, duration, remember_me = SessionAuthenticationService.refresh(current_user, token)
    except AuthenticationError as exc:
        raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc
    set_session_cookie(response, request, access_token, duration, remember_me)
    return MealieAuthToken.respond(access_token, duration)


@user_router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    accept_language: Annotated[str | None, Header()] = None,
):
    # Clearing a cookie only works when the attributes match the ones it was set with, which the old
    # bare delete_cookie() call didn't manage for embedded (partitioned, SameSite=None) deployments.
    response.set_cookie(SESSION_COOKIE_NAME, "", max_age=0, expires=0, **session_cookie_attrs(request))

    translator = get_locale_provider(accept_language)
    return {"message": translator.t("notifications.logged-out")}
