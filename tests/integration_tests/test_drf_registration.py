from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from mealie.app import app
from mealie.services.event_bus_service.event_bus_service import EventBusService
from mealie.services.event_bus_service.event_types import EventTypes
from tests.utils.factories import user_registration_factory


def test_registration_publishes_signup_after_response(api_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    published: list[dict[str, Any]] = []

    async def capture_response(scope: Scope, receive: Receive, send: Send) -> None:
        async def capture_send(message: Message) -> None:
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                order.append("response")

        await app(scope, receive, capture_send)

    def publish(self: EventBusService, **kwargs: Any) -> None:
        order.append("event")
        published.append(kwargs)

    monkeypatch.setattr(EventBusService, "_publish_event", publish)
    registration = user_registration_factory()
    client = TestClient(capture_response)
    response = client.post("/api/users/register", json=registration.model_dump(by_alias=True))
    assert response.status_code == 201
    assert order == ["response", "event"]
    assert str(published[0]["group_id"]) == response.json()["groupId"]
    assert str(published[0]["household_id"]) == response.json()["householdId"]
    event = published[0]["event"]
    assert event.event_type == EventTypes.user_signup
    assert event.integration_id == "registration"
    assert "password" not in response.json()


def test_unknown_password_reset_email_returns_json_null(api_client: TestClient) -> None:
    response = api_client.post("/api/users/forgot-password", json={"email": "missing-user@example.invalid"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.content == b"null"


def test_registration_password_mismatch_does_not_create_user(api_client: TestClient) -> None:
    registration = user_registration_factory().model_dump(by_alias=True)
    registration["passwordConfirm"] = "does-not-match"
    response = api_client.post("/api/users/register", json=registration)
    assert response.status_code == 422
    response = api_client.post(
        "/api/auth/token", data={"username": registration["username"], "password": registration["password"]}
    )
    assert response.status_code == 401
