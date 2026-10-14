from datetime import timedelta

from asgiref.sync import async_to_sync
from django.http import HttpResponse
from pydantic import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from starlette.requests import Request as ASGIRequest
from starlette.responses import Response as CookieResponse

from mealie.core.config import get_app_settings
from mealie.core.security.authentication import SessionAuthenticationService
from mealie.core.security.session_cookies import SESSION_COOKIE_NAME, session_cookie_attrs, set_session_cookie
from mealie.drf.base import MealieAPIView, SessionAPIView, UserAPIView
from mealie.lang import get_locale_provider
from mealie.schema.user.auth import CredentialsRequest, NativeOIDCTokenRequest
from mealie.services.oidc_service import OIDCService


def token_response(request: Request, token: str, duration: timedelta, remember_me: bool) -> Response:
    # Reuse the established cookie encoder, including partitioned embedded cookies.
    cookie_response = CookieResponse()
    set_session_cookie(cookie_response, ASGIRequest(request._request.scope), token, duration, remember_me)
    return Response(
        {"access_token": token, "token_type": "bearer", "expires_in": int(duration.total_seconds())},
        headers={"Set-Cookie": cookie_response.headers["set-cookie"]},
    )


class LoginView(SessionAPIView):
    authentication_classes: list = []
    permission_classes: list = []
    http_method_names = ["post"]
    form_body = True

    def post(self, request: Request) -> Response:
        # The existing endpoint accepts form credentials, never JSON credentials.
        data = self.parsed_form or {}
        try:
            credentials = CredentialsRequest(
                username=data.get("username") or "",
                password=data.get("password") or "",
                remember_me=data.get("remember_me") or False,
            )
        except ValidationError as exc:
            return self.validation_error(exc)
        ip = request.headers.get("x-forwarded-for", "").split(",")[0]
        if not ip:
            client = ASGIRequest(request._request.scope).client
            ip = client.host if client else "unknown"
        token, duration = SessionAuthenticationService(self.db).login(credentials, ip)
        return token_response(request, token, duration, credentials.remember_me)


class RefreshView(UserAPIView):
    http_method_names = ["post"]

    def post(self, request: Request) -> Response:
        token, duration, remember_me = SessionAuthenticationService.refresh(request.user, request.auth)
        return token_response(request, token, duration, remember_me)


class LogoutView(UserAPIView):
    http_method_names = ["post"]

    def post(self, request: Request) -> Response:
        cookie_response = CookieResponse()
        cookie_response.set_cookie(
            SESSION_COOKIE_NAME,
            "",
            max_age=0,
            expires=0,
            **session_cookie_attrs(ASGIRequest(request._request.scope)),
        )
        translator = get_locale_provider(request.headers.get("accept-language"))
        return Response(
            {"message": translator.t("notifications.logged-out")},
            headers={"Set-Cookie": cookie_response.headers["set-cookie"]},
        )


class OAuthLoginView(MealieAPIView):
    authentication_classes: list = []
    permission_classes: list = []
    http_method_names = ["get"]

    def get(self, request: Request) -> HttpResponse:
        result = async_to_sync(OIDCService().login)(ASGIRequest(request._request.scope))
        return HttpResponse(result.body, status=result.status_code, headers=dict(result.headers))


class OAuthCallbackView(SessionAPIView):
    authentication_classes: list = []
    permission_classes: list = []
    http_method_names = ["get"]

    def get(self, request: Request) -> Response:
        token, duration = async_to_sync(OIDCService(self.db).callback)(ASGIRequest(request._request.scope))
        return token_response(request, token, duration, get_app_settings().OIDC_REMEMBER_ME)


class OAuthNativeConfigView(OAuthLoginView):
    def get(self, request: Request) -> Response:
        result = async_to_sync(OIDCService().native_config)()
        return Response(result.model_dump(mode="json"))


class OAuthNativeTokenView(SessionAPIView):
    authentication_classes: list = []
    permission_classes: list = []
    http_method_names = ["post"]
    body_schema = NativeOIDCTokenRequest

    def post(self, request: Request) -> Response:
        try:
            data = self.validated_body(NativeOIDCTokenRequest)
        except ValidationError as exc:
            return self.validation_error(exc)
        token, duration = async_to_sync(OIDCService(self.db).native_token)(data)
        return token_response(request, token, duration, get_app_settings().OIDC_REMEMBER_ME)
