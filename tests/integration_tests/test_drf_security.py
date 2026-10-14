from datetime import timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mealie.app import app
from mealie.core.config import get_app_settings
from mealie.core.security.tokens import ALGORITHM, create_access_token
from mealie.middleware.locale_context import LocaleContextMiddleware
from mealie.routes import router
from mealie.routes.handlers import register_debug_handler
from tests import data as test_data
from tests.utils.fixture_schemas import TestUser


@pytest.fixture(scope="module")
def legacy_client(api_client: TestClient):
    legacy = FastAPI()
    legacy.include_router(router)
    legacy.add_middleware(LocaleContextMiddleware)
    legacy.dependency_overrides = app.dependency_overrides
    register_debug_handler(legacy)
    with TestClient(legacy) as client:
        yield client


@pytest.mark.parametrize("path", ["/api/admin/about", "/api/admin/about/statistics", "/api/admin/about/check"])
def test_drf_admin_requires_admin(api_client: TestClient, unique_user: TestUser, path: str) -> None:
    anonymous = api_client.get(path)
    assert anonymous.status_code == 401
    assert anonymous.headers["www-authenticate"] == "Bearer"
    denied = api_client.get(path, headers=unique_user.token)
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Forbidden"}


@pytest.mark.parametrize("kind", ["expired", "wrong-signature", "deleted-user"])
def test_drf_rejects_invalid_session(api_client: TestClient, unique_user: TestUser, kind: str) -> None:
    claims = {"sub": str(unique_user.user_id)}
    if kind == "expired":
        token, _ = create_access_token(claims, timedelta(seconds=-1))
    elif kind == "wrong-signature":
        token = jwt.encode(claims, "incorrect-signing-key" * 3, algorithm=ALGORITHM)
    else:
        token, _ = create_access_token({"sub": str(uuid4())})
    response = api_client.get("/api/users/self", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_drf_cookie_auth_and_header_precedence(api_client: TestClient, unique_user: TestUser) -> None:
    token = unique_user.token["Authorization"].split(" ", 1)[1]
    api_client.cookies.set("mealie.access_token", token)
    response = api_client.get("/api/users/self")
    assert response.status_code == 200
    assert response.json()["id"] == str(unique_user.user_id)
    for private_field in ["password", "loginAttemps", "tokensValidAfter", "lockedAt"]:
        assert private_field not in response.json()
    assert api_client.get("/api/users/self", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert api_client.get("/api/users/self", headers={"Authorization": "Bearer "}).status_code == 401


def test_drf_revoked_api_token_rejected(api_client: TestClient, unique_user: TestUser) -> None:
    created = api_client.post("/api/users/api-tokens", json={"name": "Revocation check"}, headers=unique_user.token)
    assert created.status_code == 201
    data = created.json()
    bearer = {"Authorization": f"Bearer {data['token']}"}
    assert api_client.get("/api/users/self", headers=bearer).status_code == 200
    assert api_client.delete(f"/api/users/api-tokens/{data['id']}", headers=unique_user.token).status_code == 200
    assert api_client.get("/api/users/self", headers=bearer).status_code == 401


def test_drf_api_tokens_are_group_scoped(
    api_client: TestClient, unique_user: TestUser, user_tuple: list[TestUser]
) -> None:
    outsider = user_tuple[0]
    assert outsider.group_id != unique_user.group_id
    created = api_client.post("/api/users/api-tokens", json={"name": "Group scope check"}, headers=unique_user.token)
    assert created.status_code == 201
    path = f"/api/users/api-tokens/{created.json()['id']}"
    assert api_client.delete(path, headers=outsider.token).status_code == 404
    assert api_client.delete(path, headers=unique_user.token).status_code == 200


def test_drf_embedded_cookie_attributes(api_client: TestClient, unique_user: TestUser) -> None:
    headers = {"x-forwarded-proto": "https", "x-mealie-embedded": "true"}
    response = api_client.post(
        "/api/auth/token", data={"username": unique_user.email, "password": unique_user.password}, headers=headers
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "SameSite=none" in cookie and "Partitioned" in cookie
    token = response.json()["access_token"]
    response = api_client.post("/api/auth/logout", headers={**headers, "Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "Max-Age=0" in cookie
    assert "Secure" in cookie and "SameSite=none" in cookie and "Partitioned" in cookie


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/auth/refresh", {}),
        ("post", "/api/users/self", {}),
        ("put", "/api/users/self", {}),
        ("get", "/api/users/api-tokens", {}),
        ("get", "/api/users/00000000-0000-4000-8000-000000000000/favorites/example", {}),
        ("get", "/api/users/self", {}),
        ("post", "/api/auth/logout", {}),
        ("get", "/api/admin/about", {}),
        ("post", "/api/users/api-tokens", {"content": "{", "headers": {"Content-Type": "application/json"}}),
        ("post", "/api/auth/token", {"data": {"remember_me": "invalid-boolean"}}),
        ("post", "/api/auth/token", {"json": {"username": "unknown", "password": "ignored"}}),
    ],
)
def test_drf_error_contract(
    api_client: TestClient, legacy_client: TestClient, method: str, path: str, kwargs: dict
) -> None:
    legacy_client.cookies.clear()
    expected = legacy_client.request(method, path, **kwargs)
    actual = api_client.request(method, path, **kwargs)
    assert actual.status_code == expected.status_code
    expected_body = expected.json()
    if "message" in expected_body:
        # FastAPI's debug-only traceback points at the legacy source file. The
        # validation diagnostics and envelope are the contract, not that location.
        expected_body["message"] = expected_body["message"].split('  File "', 1)[0].rstrip()
    assert actual.json() == expected_body
    assert actual.headers.get("www-authenticate") == expected.headers.get("www-authenticate")
    assert actual.headers.get("allow") == expected.headers.get("allow")


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/api/users/api-tokens", {"json": {}}),
        ("post", "/api/users/api-tokens", {}),
        ("post", "/api/users/api-tokens", {"json": []}),
        ("post", "/api/users/api-tokens", {"content": "{", "headers": {"Content-Type": "application/json"}}),
        ("put", "/api/users/password", {"json": {"newPassword": "short"}}),
        (
            "put",
            "/api/users/password",
            {
                "json": {"currentPassword": "wrong", "newPassword": "valid-long-password"},
                "headers": {"Accept-Language": "fr-FR"},
            },
        ),
        ("delete", "/api/users/api-tokens/not-an-integer", {}),
        ("delete", "/api/users/api-tokens/-999", {}),
    ],
)
def test_drf_authenticated_error_contract(
    api_client: TestClient, legacy_client: TestClient, unique_user: TestUser, method: str, path: str, kwargs: dict
) -> None:
    options = {**kwargs}
    headers = {**unique_user.token, **options.pop("headers", {})}
    expected = legacy_client.request(method, path, headers=headers, **options)
    actual = api_client.request(method, path, headers=headers, **options)
    assert actual.status_code == expected.status_code
    expected_body = expected.json()
    if "message" in expected_body:
        expected_body["message"] = expected_body["message"].split('  File "', 1)[0].rstrip()
    assert actual.json() == expected_body


def test_drf_overlapping_method_retains_legacy_validation(
    api_client: TestClient, legacy_client: TestClient, unique_user: TestUser
) -> None:
    expected = legacy_client.put("/api/users/self", headers=unique_user.token)
    actual = api_client.put("/api/users/self", headers=unique_user.token)
    assert actual.status_code == expected.status_code == 422
    assert actual.json() == expected.json()


def test_drf_production_validation_format(
    api_client: TestClient, unique_user: TestUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_app_settings(), "TESTING", False)
    response = api_client.post("/api/users/api-tokens", json={}, headers=unique_user.token)
    assert response.status_code == 422
    assert response.json() == {
        "detail": [{"type": "missing", "loc": ["body", "name"], "msg": "Field required", "input": {}}]
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"data": {"profile": ""}},
        {"data": {"profile": "not-a-file"}},
        {"content": b"invalid", "headers": {"Content-Type": "multipart/form-data"}},
    ],
)
def test_drf_image_validation_contract(
    api_client: TestClient, legacy_client: TestClient, unique_user: TestUser, kwargs: dict
) -> None:
    options = {**kwargs}
    headers = {**unique_user.token, **options.pop("headers", {})}
    path = f"/api/users/{unique_user.user_id}/image"
    expected = legacy_client.post(path, headers=headers, **options)
    actual = api_client.post(path, headers=headers, **options)
    assert actual.status_code == expected.status_code
    expected_body = expected.json()
    if "message" in expected_body:
        expected_body["message"] = expected_body["message"].split('  File "', 1)[0].rstrip()
    assert actual.json() == expected_body


def test_drf_image_owner_only(api_client: TestClient, unique_user: TestUser, user_tuple: list[TestUser]) -> None:
    target = user_tuple[0]
    media_path = f"/api/media/users/{target.user_id}/profile.webp"
    before = api_client.get(media_path)
    assert before.status_code == 200
    response = api_client.post(
        f"/api/users/{target.user_id}/image",
        headers=unique_user.token,
        files={"profile": ("picture.jpg", test_data.images_test_image_1.read_bytes(), "image/jpeg")},
    )
    assert response.status_code == 403
    assert api_client.get(media_path).content == before.content


def test_drf_image_upload_returns_json_null(api_client: TestClient, unique_user: TestUser) -> None:
    response = api_client.post(
        f"/api/users/{unique_user.user_id}/image",
        headers=unique_user.token,
        files={"profile": ("picture.jpg", test_data.images_test_image_1.read_bytes(), "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.content == b"null"
    assert response.headers["content-type"] == "application/json"
