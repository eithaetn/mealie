from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session
from starlette.datastructures import URLPath
from starlette.requests import Request
from starlette.responses import RedirectResponse

from mealie.core.api_error import APIError
from mealie.core.config import get_app_settings
from mealie.core.exceptions import MissingClaimException
from mealie.core.root_logger import get_logger
from mealie.core.security.auth_cache import AuthCache
from mealie.schema.user.auth import NativeOIDCTokenRequest, OIDCNativeConfig
from mealie.services._base_service import BaseService

logger = get_logger("auth")


settings = get_app_settings()
oauth = None
if settings.OIDC_READY:
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth(cache=AuthCache())
    scope = None
    if settings.OIDC_SCOPES_OVERRIDE:
        scope = settings.OIDC_SCOPES_OVERRIDE
    else:
        groups_claim = settings.OIDC_GROUPS_CLAIM if settings.OIDC_REQUIRES_GROUP_CLAIM else ""
        scope = f"openid email profile {groups_claim}"
    client_args: dict[str, Any] = {"scope": scope.rstrip()}
    if settings.OIDC_CLIENT_TIMEOUT != "default":
        client_args["timeout"] = settings.OIDC_CLIENT_TIMEOUT if settings.OIDC_CLIENT_TIMEOUT != "None" else None
    if settings.OIDC_TLS_CACERTFILE:
        client_args["verify"] = settings.OIDC_TLS_CACERTFILE

    oauth.register(
        "oidc",
        client_id=settings.OIDC_CLIENT_ID,
        client_secret=settings.OIDC_CLIENT_SECRET,
        server_metadata_url=settings.OIDC_CONFIGURATION_URL,
        client_kwargs=client_args,
        code_challenge_method="S256",
    )


class OIDCService(BaseService):
    def __init__(self, session: Session | None = None) -> None:
        super().__init__()
        self.session = session

    @staticmethod
    def client() -> Any:
        if not oauth:
            raise APIError(500, "Could not initialize OAuth client")
        return oauth.create_client("oidc")

    async def login(self, request: Request) -> RedirectResponse:
        client = self.client()
        if not settings.PRODUCTION:
            redirect_url = "http://localhost:3000/login"
        else:
            base = (settings.BASE_URL or request.base_url) if not settings.is_default_base_url else request.base_url
            redirect_url = URLPath("/login").make_absolute_url(base)
        return await client.authorize_redirect(request, redirect_url)

    async def authenticate_userinfo(self, client: Any, token: dict, userinfo: Any) -> tuple[str, timedelta]:
        from mealie.core.security.providers.openid_provider import OpenIDProvider

        assert self.session is not None
        try:
            auth = OpenIDProvider(self.session, userinfo).authenticate()
        except MissingClaimException:
            try:
                logger.debug("[OIDC] Claims not present in the ID token, pulling user info")
                userinfo = await client.userinfo(token=token)
                auth = OpenIDProvider(self.session, userinfo, use_default_groups=True).authenticate()
            except MissingClaimException:
                logger.error("[OIDC] Required claims not present in ID token or userinfo endpoint")
                auth = None
        if not auth:
            raise APIError(401, "Unauthorized")
        return auth

    async def callback(self, request: Request) -> tuple[str, timedelta]:
        client = self.client()
        token = await client.authorize_access_token(request)
        return await self.authenticate_userinfo(client, token, token["userinfo"])

    async def native_config(self) -> OIDCNativeConfig:
        if not settings.OIDC_READY or not oauth:
            raise APIError(404, "OIDC is not configured")
        client = self.client()
        metadata = await client.load_server_metadata()
        return OIDCNativeConfig(
            authorization_endpoint=metadata["authorization_endpoint"],
            client_id=client.client_id,
            scope=client.client_kwargs.get("scope", "openid email profile"),
        )

    async def native_token(self, data: NativeOIDCTokenRequest) -> tuple[str, timedelta]:
        if not settings.OIDC_READY or not oauth:
            raise APIError(404, "OIDC is not configured")
        from authlib.integrations.starlette_client import OAuthError

        client = self.client()
        try:
            token = await client.fetch_access_token(
                code=data.code, code_verifier=data.code_verifier, redirect_uri=data.redirect_uri
            )
            userinfo = await client.parse_id_token(token, nonce=data.nonce)
        except OAuthError as exc:
            logger.error("[OIDC] Native token exchange failed: %s", exc)
            raise APIError(401, "Unauthorized") from exc
        return await self.authenticate_userinfo(client, token, userinfo)
