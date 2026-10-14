from collections.abc import Iterator
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from mealie.core.config import get_app_settings
from mealie.drf.dispatch import DjangoAPIMiddleware
from mealie.routes.handlers import register_debug_handler
from mealie.routes.households.controller_household_self_service import router as household_router
from mealie.routes.households.controller_invitations import router as invitation_router
from mealie.services.email.email_service import EmailService
from tests.integration_tests.test_drf_groups import assert_contract
from tests.utils.fixture_schemas import TestUser


@pytest.fixture(scope="module")
def legacy_client() -> Iterator[TestClient]:
    legacy = FastAPI()
    legacy.include_router(household_router, prefix="/api")
    legacy.include_router(invitation_router, prefix="/api")
    register_debug_handler(legacy)
    with TestClient(legacy, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize("path", ["self", "preferences", "statistics", "members?perPage=1", "self/recipes/missing"])
def test_household_read_contract(
    api_client: TestClient, legacy_client: TestClient, unique_user: TestUser, path: str
) -> None:
    path = f"/api/households/{path}"
    actual = api_client.get(path, headers=unique_user.token)
    assert actual.status_code == (404 if path.endswith("missing") else 200)
    assert_contract(actual, legacy_client.get(path, headers=unique_user.token))


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "self"),
        ("get", "members"),
        ("get", "preferences"),
        ("put", "preferences"),
        ("put", "permissions"),
        ("get", "statistics"),
        ("get", "self/recipes/missing"),
        ("get", "invitations"),
        ("post", "invitations"),
        ("post", "invitations/email"),
    ],
)
def test_household_requires_authentication(api_client: TestClient, method: str, path: str) -> None:
    response = api_client.request(method, f"/api/households/{path}")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "path,options",
    [
        ("members?page=invalid", {}),
        ("members?orderBy=random", {}),
        ("permissions", {"json": {}}),
        ("permissions", {"json": {"userId": "bad-uuid"}}),
        ("preferences", {"json": {"recipePublic": "invalid"}}),
        ("invitations", {"json": {}}),
        ("invitations", {"json": {"uses": "invalid"}}),
        ("invitations/email", {"json": {}}),
    ],
)
def test_household_validation_contract(
    api_client: TestClient, legacy_client: TestClient, unique_user: TestUser, path: str, options: dict[str, Any]
) -> None:
    method = "get" if path.startswith("members") else "post" if path.startswith("invitations") else "put"
    path = f"/api/households/{path}"
    assert_contract(
        api_client.request(method, path, headers=unique_user.token, **options),
        legacy_client.request(method, path, headers=unique_user.token, **options),
    )


def test_household_members_cannot_escape_household(
    api_client: TestClient, unique_user: TestUser, h2_user: TestUser, g2_user: TestUser
) -> None:
    response = api_client.get("/api/households/members", headers=unique_user.token, params={"perPage": -1})
    assert response.status_code == 200
    assert response.json()["items"]
    for item in response.json()["items"]:
        assert item["householdId"] == unique_user.household_id
        assert item["groupId"] == unique_user.group_id
        assert "password" not in item
        assert "tokensValidAfter" not in item
    for target in [h2_user, g2_user]:
        filtered = api_client.get(
            "/api/households/members",
            headers=unique_user.token,
            params={"queryFilter": f'householdId="{target.household_id}"'},
        )
        assert filtered.status_code == 200
        assert filtered.json()["items"] == []


def test_household_permissions_cannot_escalate_or_cross_scope(
    api_client: TestClient, legacy_client: TestClient, unique_user: TestUser, h2_user: TestUser, g2_user: TestUser
) -> None:
    for target, status in [(unique_user, 403), (h2_user, 403), (g2_user, 404)]:
        payload = {"userId": str(target.user_id), "canManage": True, "canInvite": True}
        before = target.repos.users.get_one(target.user_id).model_dump()
        actual = api_client.put("/api/households/permissions", json=payload, headers=unique_user.token)
        assert actual.status_code == status
        assert_contract(
            actual, legacy_client.put("/api/households/permissions", json=payload, headers=unique_user.token)
        )
        assert target.repos.users.get_one(target.user_id).model_dump() == before


def test_household_permissions_filter_private_fields(api_client: TestClient, user_tuple: list[TestUser]) -> None:
    actor, target = user_tuple
    original_actor = actor.repos.users.get_one(actor.user_id)
    original_target = target.repos.users.get_one(target.user_id)
    actor.repos.users.patch(actor.user_id, {"can_manage": True})
    try:
        response = api_client.put(
            "/api/households/permissions", headers=actor.token, json={"userId": str(target.user_id), "canInvite": True}
        )
        assert response.status_code == 200
        assert response.json()["canInvite"] is True
        assert "password" not in response.json()
        assert "loginAttemps" not in response.json()
    finally:
        actor.repos.users.update(actor.user_id, original_actor)
        target.repos.users.update(target.user_id, original_target)


@pytest.mark.parametrize(
    "path,payload",
    [("invitations", {"uses": 1}), ("invitations/email", {"email": "nobody@example.invalid", "token": "dummy"})],
)
def test_invitations_respect_password_login_switch(
    api_client: TestClient,
    legacy_client: TestClient,
    unique_user: TestUser,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict,
) -> None:
    monkeypatch.setattr(get_app_settings(), "ALLOW_PASSWORD_LOGIN", False)
    path = f"/api/households/{path}"
    actual = api_client.post(path, headers=unique_user.token, json=payload)
    assert actual.status_code == 403
    assert_contract(actual, legacy_client.post(path, headers=unique_user.token, json=payload))


def test_invitation_privileges(api_client: TestClient, user_tuple: list[TestUser]) -> None:
    user = user_tuple[0]
    assert not user.repos.users.get_one(user.user_id).can_invite
    assert api_client.get("/api/households/invitations", headers=user.token).status_code == 403
    assert api_client.post("/api/households/invitations", headers=user.token, json={"uses": 1}).status_code == 403
    assert (
        api_client.post(
            "/api/households/invitations/email",
            headers=user.token,
            json={"email": "nobody@example.invalid", "token": "dummy"},
        ).status_code
        == 403
    )


@pytest.mark.parametrize("failure", [False, True])
def test_invitation_email_contract(
    api_client: TestClient,
    legacy_client: TestClient,
    unique_user: TestUser,
    monkeypatch: pytest.MonkeyPatch,
    failure: bool,
) -> None:
    send = Mock(return_value=True, side_effect=RuntimeError("mail unavailable") if failure else None)
    monkeypatch.setattr(EmailService, "send_invitation", send)
    body = {"email": "nobody@example.invalid", "token": "dummy"}
    actual = api_client.post("/api/households/invitations/email", headers=unique_user.token, json=body)
    assert actual.status_code == 200
    assert actual.json()["success"] is not failure
    assert_contract(
        actual, legacy_client.post("/api/households/invitations/email", headers=unique_user.token, json=body)
    )
    assert send.call_count == 2


def test_household_drf_dispatch(unique_user: TestUser) -> None:
    async def fallback(scope: Scope, receive: Receive, send: Send) -> None:
        raise AssertionError(f"Unexpected legacy handler: {scope['path']}")

    client = TestClient(DjangoAPIMiddleware(fallback))
    for path in ["self", "preferences", "members", "statistics"]:
        assert client.get(f"/api/households/{path}", headers=unique_user.token).status_code == 200
    assert client.get("/api/households/self/recipes/missing", headers=unique_user.token).status_code == 404
    assert client.get("/api/households/invitations", headers=unique_user.token).status_code == 403
    assert client.post("/api/households/invitations", json={"uses": 1}, headers=unique_user.token).status_code == 201
