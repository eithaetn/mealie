import base64
import hashlib
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI
from fastapi.testclient import TestClient
from joserfc.errors import InvalidClaimError

from mealie.core.config import get_app_settings
from mealie.core.security.auth_cache import AuthCache
from mealie.routes.auth.auth import public_router
from mealie.services import oidc_service
from tests.utils.fixture_schemas import TestUser


@pytest.fixture
def oidc_client(monkeypatch: pytest.MonkeyPatch, unique_user: TestUser):
    settings = get_app_settings()
    monkeypatch.setattr(type(settings), "OIDC_READY", property(lambda self: True))
    monkeypatch.setattr(settings, "OIDC_USER_GROUP", "")
    monkeypatch.setattr(settings, "OIDC_ADMIN_GROUP", "")
    monkeypatch.setattr(settings, "OIDC_REQUIRES_EMAIL_VERIFICATION", True)
    registry = OAuth(cache=AuthCache())
    client = registry.register(
        "oidc",
        client_id="test-client",
        authorize_url="https://idp.example/authorize",
        access_token_url="https://idp.example/token",
        client_kwargs={"scope": "openid email profile"},
        code_challenge_method="S256",
    )
    claims = {
        "email": unique_user.email,
        "email_verified": True,
        "name": unique_user.full_name,
        "preferred_username": unique_user.username,
    }
    monkeypatch.setattr(
        client,
        "fetch_access_token",
        AsyncMock(return_value={"access_token": "idp-token", "id_token": "signed-id-token"}),
    )
    monkeypatch.setattr(client, "parse_id_token", AsyncMock(return_value=claims))
    monkeypatch.setattr(client, "userinfo", AsyncMock(return_value=claims))
    monkeypatch.setattr(oidc_service, "oauth", registry)
    return client


def test_native_oidc_uses_pkce_nonce_and_real_account_checks(
    api_client: TestClient, oidc_client, unique_user: TestUser
) -> None:
    body = {"code": "code", "code_verifier": "verifier", "redirect_uri": "mealie://callback", "nonce": "nonce"}
    response = api_client.post("/api/auth/oauth/native/token", json=body)
    assert response.status_code == 200
    oidc_client.fetch_access_token.assert_awaited_once_with(
        code=body["code"], code_verifier=body["code_verifier"], redirect_uri=body["redirect_uri"]
    )
    assert oidc_client.parse_id_token.await_args.kwargs["nonce"] == body["nonce"]
    assert "mealie.access_token=" in response.headers["set-cookie"]
    me = api_client.get("/api/users/self", headers={"Authorization": f"Bearer {response.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == str(unique_user.user_id)


def test_browser_oidc_state_pkce_and_replay_protection(api_client: TestClient, oidc_client) -> None:
    response = api_client.get("/api/auth/oauth", follow_redirects=False)
    assert response.status_code == 302
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"]
    callback = {"state": params["state"][0], "code": "authorization-code"}
    response = api_client.get("/api/auth/oauth/callback", params=callback)
    assert response.status_code == 200
    exchange = oidc_client.fetch_access_token.await_args.kwargs
    verifier = exchange["code_verifier"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == [challenge]
    assert oidc_client.parse_id_token.await_args.kwargs["nonce"] == params["nonce"][0]
    replay = api_client.get("/api/auth/oauth/callback", params=callback)
    assert replay.status_code == 500  # Preserve the existing Authlib-error response.
    assert oidc_client.fetch_access_token.await_count == 1
    assert "mealie.access_token=" not in replay.headers.get("set-cookie", "")


def test_native_oidc_unverified_email_cannot_link_account(api_client: TestClient, oidc_client) -> None:
    oidc_client.parse_id_token.return_value["email_verified"] = False
    response = api_client.post(
        "/api/auth/oauth/native/token",
        json={"code": "code", "code_verifier": "verifier", "redirect_uri": "mealie://callback"},
    )
    assert response.status_code == 401
    assert "mealie.access_token=" not in response.headers.get("set-cookie", "")


@pytest.mark.parametrize("error", [InvalidClaimError("nonce"), RuntimeError("Identity provider unavailable")])
def test_oidc_server_error_contract(api_client: TestClient, oidc_client, error: Exception) -> None:
    legacy = FastAPI()
    legacy.include_router(public_router, prefix="/api/auth")
    oidc_client.parse_id_token.side_effect = error
    body = {"code": "code", "code_verifier": "verifier", "redirect_uri": "mealie://callback", "nonce": "nonce"}
    path = "/api/auth/oauth/native/token"
    with TestClient(legacy, raise_server_exceptions=False) as client:
        expected = client.post(path, json=body)
    actual = api_client.post(path, json=body)
    assert actual.status_code == expected.status_code == 500
    assert actual.content == expected.content == b"Internal Server Error"
    assert actual.headers["content-type"] == expected.headers["content-type"]
    assert "mealie.access_token=" not in actual.headers.get("set-cookie", "")
