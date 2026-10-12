from uuid import uuid1, uuid4

import pytest
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from mealie.app import app as fastapi_app
from mealie.core.config import get_app_settings
from mealie.services.event_bus_service.event_bus_service import EventBusService
from mealie.services.event_bus_service.event_types import Event
from tests.utils.factories import random_string
from tests.utils.fixture_schemas import TestUser

# isort: split
from mealie_drf.asgi import django_app

BASE = "/api/organizers/tags"


@pytest.fixture
def clients() -> tuple[TestClient, TestClient]:
    return TestClient(django_app), TestClient(fastapi_app, raise_server_exceptions=False)


@pytest.mark.parametrize("accept", ["application/json", "text/html", "text/plain"])
def test_accept_header(clients: tuple[TestClient, TestClient], unique_user: TestUser, accept: str) -> None:
    assert_parity(clients, "get", BASE, headers={**unique_user.token, "Accept": accept})


@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/vnd.api+json", "application/json", "application/json ; charset=utf-8"]
)
def test_content_type(
    clients: tuple[TestClient, TestClient], unique_user: TestUser, production_validation: None, content_type: str
) -> None:
    assert_parity(
        clients, "post", BASE, content='{"name": 123}', headers={**unique_user.token, "Content-Type": content_type}
    )


def test_plain_serializers() -> None:
    from rest_framework.serializers import ModelSerializer, Serializer

    from mealie_drf.tags.serializers import TagInputSerializer, TagMergeSerializer, TagSerializer

    for serializer in [TagInputSerializer, TagMergeSerializer, TagSerializer]:
        assert issubclass(serializer, Serializer)
        assert not issubclass(serializer, ModelSerializer)


def test_large_invalid_body(
    clients: tuple[TestClient, TestClient], unique_user: TestUser, production_validation: None
) -> None:
    payload = b'{"name":123,"ignored":"' + b"x" * (3 * 1024 * 1024) + b'"}'
    assert (
        assert_parity(
            clients, "post", BASE, content=payload, headers={**unique_user.token, "Content-Type": "application/json"}
        )[0].status_code
        == 422
    )


def test_many_query_parameters(clients: tuple[TestClient, TestClient], unique_user: TestUser) -> None:
    assert (
        assert_parity(
            clients, "get", BASE, params={f"ignored{i}": "x" for i in range(1100)}, headers=unique_user.token
        )[0].status_code
        == 200
    )


def test_json_recursion_error(
    clients: tuple[TestClient, TestClient], unique_user: TestUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    def decoder_failure(*args: object, **kwargs: object) -> object:
        raise RecursionError("JSON nesting exceeds decoder capacity")

    with monkeypatch.context() as patch:
        patch.setattr(json, "loads", decoder_failure)
        responses = [
            client.post(BASE, content="{}", headers={**unique_user.token, "Content-Type": "application/json"})
            for client in clients
        ]
    assert responses[0].status_code == responses[1].status_code == 400
    assert responses[0].json() == responses[1].json() == {"detail": "There was an error parsing the body"}


@pytest.mark.parametrize("suffix", ["", "/slug/missing"])
def test_development_cors(unique_user: TestUser, suffix: str) -> None:
    from django.core.asgi import get_asgi_application
    from fastapi import FastAPI
    from starlette.middleware.cors import CORSMiddleware
    from starlette.middleware.gzip import GZipMiddleware
    from starlette.middleware.sessions import SessionMiddleware

    from mealie.routes.organizers.controller_tags import router
    from mealie_drf.tags.middleware import TagErrorHeaders, TagHTTPMiddleware

    cors = {
        "allow_origins": ["http://localhost:3000"],
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
    reference = FastAPI()
    reference.include_router(router, prefix="/api/organizers")
    reference.add_middleware(GZipMiddleware, minimum_size=1000)
    reference.add_middleware(SessionMiddleware, secret_key=get_app_settings().SESSION_SECRET)
    reference.add_middleware(CORSMiddleware, **cors)
    migrated = TagErrorHeaders(CORSMiddleware(TagHTTPMiddleware(get_asgi_application()), **cors))
    clients = (
        TestClient(migrated, raise_server_exceptions=False),
        TestClient(reference, raise_server_exceptions=False),
    )
    responses = assert_parity(
        clients, "get", BASE + suffix, headers={**unique_user.token, "Origin": "http://localhost:3000"}
    )
    for header in ["access-control-allow-origin", "access-control-allow-credentials"]:
        assert responses[0].headers.get(header) == responses[1].headers.get(header)


def test_debug_validation(clients: tuple[TestClient, TestClient], unique_user: TestUser) -> None:
    path = BASE + "/invalid"
    migrated, reference = [client.get(path, headers=unique_user.token).json() for client in clients]
    assert migrated.keys() == reference.keys() == {"status_code", "message", "data"}
    assert migrated["status_code"] == reference["status_code"] == 422
    assert migrated["data"] is reference["data"] is None
    assert migrated["message"].split(" File ")[0] == reference["message"].split(" File ")[0]
    assert "mealie_drf/tags/views.py" in migrated["message"]


@pytest.mark.parametrize("chunked", [False, True])
def test_body_without_content_headers(
    clients: tuple[TestClient, TestClient], unique_user: TestUser, production_validation: None, chunked: bool
) -> None:
    responses = []
    for client in clients:
        request = client.build_request("POST", BASE, content='{"name": 123}', headers=unique_user.token)
        assert "content-type" not in request.headers
        if chunked:
            del request.headers["content-length"]
        responses.append(client.send(request))
    assert responses[0].status_code == responses[1].status_code == 422
    assert responses[0].json() == responses[1].json()


@pytest.fixture
def production_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_app_settings()
    monkeypatch.setattr(settings, "PRODUCTION", True)
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setitem(fastapi_app.exception_handlers, RequestValidationError, request_validation_exception_handler)
    monkeypatch.setattr(fastapi_app, "middleware_stack", None)


@pytest.fixture
def tag(clients: tuple[TestClient, TestClient], unique_user: TestUser) -> dict:
    response = clients[0].post(BASE, json={"name": random_string()}, headers=unique_user.token)
    assert response.status_code == 201
    return response.json()


def assert_parity(clients: tuple[TestClient, TestClient], method: str, path: str, **kwargs: object) -> list:
    responses = [client.request(method, path, **kwargs) for client in clients]
    assert responses[0].status_code == responses[1].status_code
    if responses[0].status_code == 500:
        assert responses[0].text == responses[1].text == "Internal Server Error"
    else:
        assert responses[0].json() == responses[1].json()
    for header in [
        "content-type",
        "content-length",
        "last-modified",
        "cache-control",
        "www-authenticate",
        "content-encoding",
        "vary",
    ]:
        assert responses[0].headers.get(header) == responses[1].headers.get(header)
    return responses


def test_signed_session_headers(clients: tuple[TestClient, TestClient], unique_user: TestUser) -> None:
    import json
    from base64 import b64encode

    from itsdangerous import TimestampSigner

    signer = TimestampSigner(str(get_app_settings().SESSION_SECRET))
    cookie = signer.sign(b64encode(json.dumps({"test": "value"}).encode())).decode()
    try:
        for client in clients:
            client.cookies.set("session", cookie)
        responses = assert_parity(clients, "get", BASE, headers=unique_user.token)
        for response in responses:
            # Current Starlette renews signed sessions only when modified. Tags
            # never modify session state, so neither stack should renew this cookie.
            assert response.headers.get("set-cookie") is None
    finally:
        for client in clients:
            client.cookies.clear()


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("patch", ""),
        ("put", ""),
        ("post", "/empty"),
        ("patch", "/merge"),
        ("post", "/slug/missing"),
        ("options", "/invalid"),
    ],
)
def test_method_headers(clients: tuple[TestClient, TestClient], method: str, suffix: str) -> None:
    responses = assert_parity(clients, method, BASE + suffix)
    assert responses[0].status_code == 405
    assert responses[0].headers["allow"] == responses[1].headers["allow"]


def test_update_conflict(clients: tuple[TestClient, TestClient], unique_user: TestUser, tag: dict) -> None:
    target = clients[0].post(BASE, json={"name": random_string()}, headers=unique_user.token).json()
    assert (
        assert_parity(clients, "put", f"{BASE}/{target['id']}", headers=unique_user.token, json={"name": tag["name"]})[
            0
        ].status_code
        == 500
    )
    assert_parity(clients, "get", f"{BASE}/{target['id']}", headers=unique_user.token)


@pytest.mark.parametrize("language", ["en-US", "de-DE"])
def test_events_and_cookie_auth(
    clients: tuple[TestClient, TestClient], unique_user: TestUser, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    events: list[tuple[Event, object, object]] = []

    def publish(self: EventBusService, event: Event, group_id: object, household_id: object) -> None:
        events.append((event, group_id, household_id))

    monkeypatch.setattr(EventBusService, "_publish_event", publish)
    for client in clients:
        client.cookies.set("mealie.access_token", unique_user.token["Authorization"].removeprefix("Bearer "))
    try:
        assert_parity(clients, "get", BASE)
        created = clients[0].post(BASE, json={"name": random_string()}, headers={"Accept-Language": language})
        assert created.status_code == 201
        tag = created.json()
        assert events and all(str(event[1]) == unique_user.group_id for event in events)
        assert all(event[0].event_type.name == "tag_created" for event in events)
        # Updating the same object through each stack produces identical event
        # payloads and localized messages, broadcast to the same households.
        batches = []
        for client in clients:
            events.clear()
            response = client.put(
                f"{BASE}/{tag['id']}", json={"name": tag["name"]}, headers={"Accept-Language": language}
            )
            assert response.status_code == 200
            batches.append(
                [
                    (event.model_dump(mode="json", exclude={"event_id", "timestamp"}), str(group), str(household))
                    for event, group, household in events
                ]
            )
        assert batches[0] == batches[1] and batches[0]
        events.clear()
        deleted = clients[0].delete(f"{BASE}/{tag['id']}")
        assert deleted.status_code == 200 and deleted.content == b"null"
        assert events and all(event[0].event_type.name == "tag_deleted" for event in events)
    finally:
        for client in clients:
            client.cookies.clear()


def test_api_token(clients: tuple[TestClient, TestClient], unique_user: TestUser) -> None:
    response = clients[1].post("/api/users/api-tokens", json={"name": random_string()}, headers=unique_user.token)
    assert response.status_code == 201
    assert (
        assert_parity(clients, "get", BASE, headers={"Authorization": f"Bearer {response.json()['token']}"})[
            0
        ].status_code
        == 200
    )


@pytest.mark.parametrize(
    "method,suffix,kwargs",
    [
        ("post", "", {}),
        ("post", "", {"content": "null", "headers": {"Content-Type": "application/json"}}),
        ("post", "/merge", {}),
        ("post", "", {"json": []}),
        ("post", "", {"json": "invalid"}),
        ("put", "/invalid", {"json": {}}),
        ("get", "", {"params": {"page": "invalid", "perPage": "invalid"}}),
        ("get", "", {"params": {"orderDirection": "invalid"}}),
    ],
)
def test_validation_edges(
    clients: tuple[TestClient, TestClient],
    unique_user: TestUser,
    production_validation: None,
    method: str,
    suffix: str,
    kwargs: dict,
) -> None:
    kwargs = kwargs.copy()
    headers = {**unique_user.token, **kwargs.pop("headers", {})}
    assert assert_parity(clients, method, BASE + suffix, headers=headers, **kwargs)[0].status_code == 422


def test_associated_recipe_parity(clients: tuple[TestClient, TestClient], unique_user: TestUser, tag: dict) -> None:
    from tests.integration_tests.category_tag_tool_tests.test_organizers_merge import _create_recipe, _set_recipe_tags

    slug = _create_recipe(clients[1], unique_user)
    _set_recipe_tags(clients[1], unique_user, slug, [tag])
    for suffix in ["", "/empty", f"/slug/{tag['slug']}", f"/{tag['id']}"]:
        assert_parity(clients, "get", BASE + suffix, headers=unique_user.token)
    response = clients[0].get(f"{BASE}/slug/{tag['slug']}", headers=unique_user.token)
    assert response.json()["recipes"][0]["slug"] == slug


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"perPage": 1},
        {"page": 2, "perPage": 1},
        {"page": -1},
        {"page": 0},
        {"perPage": -1},
        {"perPage": 0},
        {"per_page": 1},
        {"search": "missing"},
        {"orderBy": "name", "orderDirection": "desc"},
        {"queryFilter": 'name = "missing"'},
    ],
)
def test_list_parity(params: dict, clients: tuple[TestClient, TestClient], unique_user: TestUser, tag: dict) -> None:
    assert_parity(clients, "get", BASE, headers=unique_user.token, params=params)


def test_crud_slug_empty_conflict(clients: tuple[TestClient, TestClient], unique_user: TestUser, tag: dict) -> None:
    path = f"{BASE}/{tag['id']}"
    assert_parity(clients, "get", path, headers=unique_user.token)
    assert_parity(clients, "get", f"{BASE}/slug/{tag['slug']}", headers=unique_user.token)
    assert_parity(clients, "get", f"{BASE}/empty", headers=unique_user.token)
    for client in clients:
        response = client.post(BASE, json={"name": tag["name"]}, headers=unique_user.token)
        assert response.status_code == 409
        assert response.json()["detail"]["message"] == "This item already exists."
    assert_parity(clients, "put", path, headers=unique_user.token, json={"name": random_string()})
    response = clients[0].delete(path, headers=unique_user.token)
    assert response.status_code == 200 and response.json() is None
    assert_parity(clients, "get", path, headers=unique_user.token)


@pytest.mark.parametrize(
    "method,suffix,payload",
    [
        ("get", "/invalid", None),
        ("get", f"/{uuid1()}", None),
        ("get", f"/{uuid4()}", None),
        ("get", "/slug/missing", None),
        ("put", f"/{uuid4()}", {"name": "missing"}),
        ("delete", f"/{uuid4()}", None),
        ("post", "", {}),
        ("post", "", {"name": 123}),
        ("post", "/merge", {}),
        ("post", "/merge", {"fromId": str(uuid1()), "toId": str(uuid4())}),
        ("post", "/merge", {"fromId": str(uuid4()), "toId": str(uuid4())}),
        ("get", "/merge", None),
        ("put", "/merge", {"name": "x"}),
        ("delete", "/empty", None),
        ("get", "/missing/child", None),
    ],
)
def test_error_parity(
    method: str,
    suffix: str,
    payload: dict | None,
    clients: tuple[TestClient, TestClient],
    unique_user: TestUser,
    production_validation: None,
) -> None:
    assert_parity(clients, method, BASE + suffix, json=payload, headers=unique_user.token)


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_auth_parity(clients: tuple[TestClient, TestClient], headers: dict) -> None:
    assert assert_parity(clients, "get", BASE, headers=headers)[0].status_code == 401


@pytest.mark.parametrize("suffix", ["/", "/empty/", "/merge/", "/missing/", "/slug/missing/", "///", "/missing//"])
def test_redirects(clients: tuple[TestClient, TestClient], suffix: str) -> None:
    responses = [c.get(BASE + suffix, params={"perPage": 1}, follow_redirects=False) for c in clients]
    assert responses[0].status_code == responses[1].status_code == 307
    assert responses[0].headers["location"] == responses[1].headers["location"]
    for header in ["content-type", "content-length"]:
        assert responses[0].headers.get(header) == responses[1].headers.get(header)


@pytest.mark.parametrize(
    "params",
    [
        {"orderBy": "random"},
        {"orderBy": "random", "paginationSeed": "seed"},
        {"orderBy": "random", "page": "invalid"},
        {"queryFilter": "malformed"},
    ],
)
def test_pagination_edges(
    clients: tuple[TestClient, TestClient], unique_user: TestUser, production_validation: None, params: dict
) -> None:
    assert_parity(clients, "get", BASE, headers=unique_user.token, params=params)


def test_invalid_utf8(clients: tuple[TestClient, TestClient], unique_user: TestUser) -> None:
    assert (
        assert_parity(
            clients, "post", BASE, content=b"\xff", headers={**unique_user.token, "Content-Type": "application/json"}
        )[0].status_code
        == 400
    )


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_malformed_json(clients: tuple[TestClient, TestClient], headers: dict, production_validation: None) -> None:
    assert (
        assert_parity(clients, "post", BASE, content="{", headers={**headers, "Content-Type": "application/json"})[
            0
        ].status_code
        == 422
    )


def test_permissions_and_tenants(
    clients: tuple[TestClient, TestClient], unique_user: TestUser, g2_user: TestUser, h2_user: TestUser, tag: dict
) -> None:
    path = f"{BASE}/{tag['id']}"
    assert_parity(clients, "get", path, headers=h2_user.token)
    assert assert_parity(clients, "get", path, headers=g2_user.token)[0].status_code == 404
    assert_parity(clients, "get", f"{BASE}/slug/{tag['slug']}", headers=g2_user.token)
    assert_parity(clients, "get", BASE, headers=g2_user.token)
    # Preserve the original get_empty repository's unscoped query explicitly.
    responses = assert_parity(clients, "get", BASE + "/empty", headers=g2_user.token)
    assert tag["id"] in [item["id"] for item in responses[0].json()]
    user = unique_user.repos.users.get_one(unique_user.user_id)
    original = user.can_organize
    user.can_organize = False
    unique_user.repos.users.update(user.id, user)
    try:
        for method, url, payload in [
            ("post", BASE, {"name": random_string()}),
            ("put", path, {"name": "denied"}),
            ("delete", path, None),
            ("post", BASE + "/merge", {"fromId": tag["id"], "toId": tag["id"]}),
        ]:
            assert assert_parity(clients, method, url, json=payload, headers=unique_user.token)[0].status_code == 403
        assert assert_parity(clients, "get", path, headers=unique_user.token)[0].status_code == 200
    finally:
        user.can_organize = original
        unique_user.repos.users.update(user.id, user)


def test_merge(clients: tuple[TestClient, TestClient], unique_user: TestUser, tag: dict) -> None:
    target = clients[0].post(BASE, json={"name": random_string()}, headers=unique_user.token).json()
    assert (
        assert_parity(
            clients, "post", BASE + "/merge", json={"fromId": tag["id"], "toId": tag["id"]}, headers=unique_user.token
        )[0].status_code
        == 400
    )
    response = clients[0].post(
        BASE + "/merge", json={"fromId": tag["id"], "toId": target["id"]}, headers=unique_user.token
    )
    assert response.status_code == 200 and response.json()["id"] == target["id"]
    assert_parity(clients, "get", f"{BASE}/{target['id']}", headers=unique_user.token)
    assert assert_parity(clients, "get", f"{BASE}/{tag['id']}", headers=unique_user.token)[0].status_code == 404
