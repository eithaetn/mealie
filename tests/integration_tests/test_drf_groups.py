from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from starlette.types import Receive, Scope, Send

from mealie.app import app
from mealie.core.config import get_app_settings
from mealie.drf.dispatch import DjangoAPIMiddleware
from mealie.middleware.locale_context import LocaleContextMiddleware
from mealie.routes.groups.controller_group_households import router as households_router
from mealie.routes.groups.controller_group_self_service import router as groups_router
from mealie.routes.handlers import register_debug_handler
from tests.utils.fixture_schemas import TestUser


@pytest.fixture(scope="module")
def legacy_client(api_client: TestClient) -> Iterator[TestClient]:
    legacy = FastAPI()
    legacy.include_router(groups_router, prefix="/api")
    legacy.include_router(households_router, prefix="/api")
    legacy.add_middleware(LocaleContextMiddleware)
    legacy.dependency_overrides = app.dependency_overrides
    register_debug_handler(legacy)
    with TestClient(legacy, raise_server_exceptions=False) as client:
        yield client


def assert_contract(actual: Response, expected: Response) -> None:
    assert actual.status_code == expected.status_code
    for header in ["content-type", "www-authenticate", "allow"]:
        assert actual.headers.get(header) == expected.headers.get(header)
    if "application/json" not in actual.headers.get("content-type", ""):
        assert actual.content == expected.content
        return
    actual_body, expected_body = actual.json(), expected.json()
    for body in [actual_body, expected_body]:
        if isinstance(body, dict) and "message" in body:
            # Only the legacy debug traceback names the FastAPI source location.
            body["message"] = body["message"].split('  File "', 1)[0].rstrip()
    assert actual_body == expected_body


@pytest.mark.parametrize("path", ["self", "preferences", "storage", "members", "households"])
def test_group_response_contract(
    api_client: TestClient, legacy_client: TestClient, unique_user: TestUser, path: str
) -> None:
    path = f"/api/groups/{path}"
    actual = api_client.get(path, headers=unique_user.token)
    assert actual.status_code == 200
    assert_contract(actual, legacy_client.get(path, headers=unique_user.token))


@pytest.mark.parametrize("admin", [False, True])
def test_group_preferences_effective_manage_permission(
    api_client: TestClient, legacy_client: TestClient, unique_user: TestUser, admin: bool
) -> None:
    user = unique_user.repos.users.get_one(unique_user.user_id)
    before = api_client.get("/api/groups/preferences", headers=unique_user.token).json()
    unique_user.repos.users.patch(unique_user.user_id, {"can_manage": False, "admin": admin})
    try:
        body = {"privateGroup": not before["privateGroup"]}
        actual = api_client.put("/api/groups/preferences", json=body, headers=unique_user.token)
        # The existing user model grants can_manage when admin is enabled.
        assert actual.status_code == (200 if admin else 403)
        assert_contract(actual, legacy_client.put("/api/groups/preferences", json=body, headers=unique_user.token))
        if not admin:
            assert api_client.get("/api/groups/preferences", headers=unique_user.token).json() == before
    finally:
        unique_user.repos.users.patch(unique_user.user_id, {"can_manage": user.can_manage, "admin": user.admin})
        assert api_client.put("/api/groups/preferences", json=before, headers=unique_user.token).status_code == 200


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"content": "null", "headers": {"content-type": "application/json"}},
        {"json": []},
        {"json": {"privateGroup": "invalid"}},
        {"content": "{", "headers": {"content-type": "application/json"}},
        {"json": {}},
        {"json": {"private_group": False, "show_announcements": True}},
        {"json": {"privateGroup": True, "showAnnouncements": False}},
    ],
)
def test_group_preferences_body_contract(
    api_client: TestClient, legacy_client: TestClient, unique_user: TestUser, options: dict[str, Any]
) -> None:
    options = dict(options)
    headers = {**unique_user.token, **options.pop("headers", {})}
    path = "/api/groups/preferences"
    before = api_client.get(path, headers=unique_user.token).json()
    try:
        assert_contract(
            api_client.put(path, headers=headers, **options), legacy_client.put(path, headers=headers, **options)
        )
    finally:
        assert api_client.put(path, json=before, headers=unique_user.token).status_code == 200


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", path)
        for path in ["self", "preferences", "storage", "members", "members/missing", "households", "households/missing"]
    ]
    + [("put", "preferences")],
)
def test_group_anonymous_denied(api_client: TestClient, legacy_client: TestClient, method: str, path: str) -> None:
    path = f"/api/groups/{path}"
    actual = api_client.request(method, path)
    assert actual.status_code == 401
    assert_contract(actual, legacy_client.request(method, path))


@pytest.mark.parametrize("resource", ["members", "households"])
@pytest.mark.parametrize(
    "query",
    [
        "perPage=1",
        "perPage=1&page=2",
        "perPage=1&page=-1",
        "perPage=-1",
        "page=0",
        "page=999",
        "perPage=0",
        "per_page=1",
        "perPage=1&perPage=2",
        "unknown=ignored",
        "orderBy=id&orderDirection=asc&orderByNullPosition=last",
        "orderBy=random&paginationSeed=stable",
        "orderBy=random",
        "queryFilter=invalid",
        "page=invalid",
        "perPage=1.5",
        "orderDirection=invalid",
        "orderByNullPosition=invalid",
        "page=invalid&perPage=invalid&orderDirection=invalid",
        "perPage=",
        "orderBy=",
    ],
)
def test_group_pagination_contract(
    api_client: TestClient,
    legacy_client: TestClient,
    unique_user: TestUser,
    h2_user: TestUser,
    resource: str,
    query: str,
) -> None:
    path = f"/api/groups/{resource}?{query}"
    assert_contract(api_client.get(path, headers=unique_user.token), legacy_client.get(path, headers=unique_user.token))


@pytest.mark.parametrize("resource", ["members", "households"])
def test_group_pagination_is_scoped(
    api_client: TestClient, unique_user: TestUser, h2_user: TestUser, g2_user: TestUser, resource: str
) -> None:
    path = f"/api/groups/{resource}"
    response = api_client.get(
        path,
        headers=unique_user.token,
        params={"perPage": -1, "groupId": g2_user.group_id, "householdId": g2_user.household_id},
    )
    assert response.status_code == 200
    body = response.json()
    expected_ids = (
        {str(unique_user.user_id), str(h2_user.user_id)}
        if resource == "members"
        else {unique_user.household_id, h2_user.household_id}
    )
    # Registration also creates an empty default household in the same group.
    assert expected_ids <= {item["id"] for item in body["items"]}
    assert all(item["groupId"] == unique_user.group_id for item in body["items"])
    assert body["total"] == body["per_page"] == len(body["items"])
    if resource == "members":
        assert all(set(item) == {"id", "groupId", "householdId", "username", "fullName"} for item in body["items"])
    # Query filters must narrow the tenant-scoped query, never replace its scope.
    filtered = api_client.get(path, headers=unique_user.token, params={"queryFilter": f'groupId="{g2_user.group_id}"'})
    assert filtered.status_code == 200
    assert filtered.json()["items"] == []


@pytest.mark.parametrize(
    "resource,key", [("members", "id"), ("members", "name"), ("households", "id"), ("households", "name")]
)
def test_group_lookup_is_scoped(
    api_client: TestClient,
    legacy_client: TestClient,
    unique_user: TestUser,
    h2_user: TestUser,
    g2_user: TestUser,
    resource: str,
    key: str,
) -> None:
    for target, status in [(h2_user, 200), (g2_user, 404)]:
        if resource == "members":
            identifier = str(target.user_id) if key == "id" else target.username
        else:
            # Default household slugs can be identical across different groups.
            household = (
                target.repos.households.create({"name": f"outside-{target.user_id}-{key}"})
                if target is g2_user
                else target.repos.households.get_one(target.household_id)
            )
            identifier = str(household.id) if key == "id" else household.slug
        path = f"/api/groups/{resource}/{identifier}"
        actual = api_client.get(path, headers=unique_user.token)
        assert actual.status_code == status
        assert_contract(actual, legacy_client.get(path, headers=unique_user.token))


def test_household_slug_collision_stays_in_group(
    api_client: TestClient, unique_user: TestUser, h2_user: TestUser, g2_user: TestUser
) -> None:
    own = h2_user.repos.households.get_one(h2_user.household_id)
    other = g2_user.repos.households.create({"name": own.name})
    assert own.slug == other.slug
    response = api_client.get(f"/api/groups/households/{own.slug}", headers=unique_user.token)
    assert response.status_code == 200
    assert response.json()["id"] == str(own.id)
    assert response.json()["groupId"] == unique_user.group_id


def test_group_reads_do_not_require_manage_permission(api_client: TestClient, user_tuple: list[TestUser]) -> None:
    user = user_tuple[0]
    assert not user.repos.users.get_one(user.user_id).can_manage
    for path in [
        "self",
        "preferences",
        "storage",
        "members",
        f"members/{user.user_id}",
        "households",
        f"households/{user.household_id}",
    ]:
        assert api_client.get(f"/api/groups/{path}", headers=user.token).status_code == 200


def test_group_preferences_cannot_target_other_group(
    api_client: TestClient, unique_user: TestUser, g2_user: TestUser
) -> None:
    path = "/api/groups/preferences"
    own = api_client.get(path, headers=unique_user.token).json()
    other = api_client.get(path, headers=g2_user.token).json()
    try:
        result = api_client.put(
            path,
            headers=unique_user.token,
            json={"groupId": g2_user.group_id, "id": other["id"], "privateGroup": not own["privateGroup"]},
        )
        assert result.status_code == 200
        assert result.json()["groupId"] == unique_user.group_id
        assert result.json()["privateGroup"] is not own["privateGroup"]
        assert api_client.get(path, headers=g2_user.token).json() == other
    finally:
        assert api_client.put(path, headers=unique_user.token, json=own).status_code == 200


def test_group_endpoints_execute_without_legacy_routes(unique_user: TestUser) -> None:
    async def unexpected_fallback(scope: Scope, receive: Receive, send: Send) -> None:
        raise AssertionError(f"Unexpected legacy dispatch: {scope['path']}")

    client = TestClient(DjangoAPIMiddleware(unexpected_fallback))
    for path in [
        "self",
        "preferences",
        "storage",
        "members",
        f"members/{unique_user.user_id}",
        "households",
        f"households/{unique_user.household_id}",
    ]:
        assert client.get(f"/api/groups/{path}", headers=unique_user.token).status_code == 200
    preferences = client.get("/api/groups/preferences", headers=unique_user.token).json()
    assert client.put("/api/groups/preferences", headers=unique_user.token, json=preferences).status_code == 200


@pytest.mark.parametrize("resource", ["members", "households"])
def test_group_query_production_validation_contract(
    api_client: TestClient, unique_user: TestUser, monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    monkeypatch.setattr(get_app_settings(), "TESTING", False)
    legacy = FastAPI()
    legacy.include_router(groups_router, prefix="/api")
    legacy.include_router(households_router, prefix="/api")
    path = f"/api/groups/{resource}?page=invalid&orderDirection=invalid"
    with TestClient(legacy) as client:
        expected = client.get(path, headers=unique_user.token)
    actual = api_client.get(path, headers=unique_user.token)
    assert actual.status_code == 422
    assert "detail" in actual.json()
    assert_contract(actual, expected)


@pytest.mark.parametrize("resource", ["members", "households"])
def test_group_authentication_precedes_query_validation(
    api_client: TestClient, legacy_client: TestClient, resource: str
) -> None:
    path = f"/api/groups/{resource}?page=invalid&orderBy=random"
    actual = api_client.get(path)
    assert actual.status_code == 401
    assert_contract(actual, legacy_client.get(path))


@pytest.mark.parametrize("resource", ["members", "households"])
def test_admin_group_reads_remain_scoped(
    api_client: TestClient, unique_admin: TestUser, unique_user: TestUser, g2_user: TestUser, resource: str
) -> None:
    response = api_client.get(f"/api/groups/{resource}", params={"perPage": -1}, headers=unique_admin.token)
    assert response.status_code == 200
    # unique_admin is moved into unique_user's group by the fixture.
    assert response.json()["items"]
    assert all(item["groupId"] == unique_user.group_id for item in response.json()["items"])
    identifier = g2_user.user_id if resource == "members" else g2_user.household_id
    assert api_client.get(f"/api/groups/{resource}/{identifier}", headers=unique_admin.token).status_code == 404
