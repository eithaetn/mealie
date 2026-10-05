from uuid import uuid1, uuid4

import pytest
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from mealie.app import app as fastapi_app
from mealie.core.config import get_app_settings
from mealie.schema.recipe.recipe import Recipe
from mealie.schema.recipe.recipe_ingredient import RecipeIngredient
from tests.utils.factories import random_string
from tests.utils.fixture_schemas import TestUser

# isort: split
from mealie_drf.asgi import application, django_app

# isort: split
from django.urls import resolve

from mealie_drf.units.serializers import UnitInputSerializer, UnitSerializer


@pytest.fixture
def django_units_client() -> TestClient:
    return TestClient(django_app)


@pytest.fixture
def fastapi_units_client() -> TestClient:
    # This remains the original reference even when api_client uses the dispatcher.
    return TestClient(fastapi_app)


@pytest.fixture
def production_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reproduce the handler selected at production startup. Conftest bootstraps
    # FastAPI with its debug handler, so flags alone cannot switch that handler.
    settings = get_app_settings()
    monkeypatch.setattr(settings, "PRODUCTION", True)
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setitem(fastapi_app.exception_handlers, RequestValidationError, request_validation_exception_handler)
    monkeypatch.setattr(fastapi_app, "middleware_stack", None)


@pytest.fixture
def drf_unit(django_units_client: TestClient, unique_user: TestUser) -> dict:
    response = django_units_client.post(
        "/api/units",
        headers=unique_user.token,
        json={
            "name": random_string(),
            "pluralName": "plural",
            "description": None,
            "aliases": [{"name": "alias"}],
            "extras": {"nested": {"value": 3}},
            "standardQuantity": 2.5,
            "standardUnit": "cup",
            "useAbbreviation": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_drf_crud_and_output_parity(
    django_units_client: TestClient, fastapi_units_client: TestClient, unique_user: TestUser, drf_unit: dict
) -> None:
    path = f"/api/units/{drf_unit['id']}"
    for payload in [None, {"name": random_string(), "fraction": False, "aliases": [], "extras": None}]:
        if payload is not None:
            updated = django_units_client.put(path, json=payload, headers=unique_user.token)
            assert updated.status_code == 200
        migrated = django_units_client.get(path, headers=unique_user.token)
        reference = fastapi_units_client.get(path, headers=unique_user.token)
        assert migrated.status_code == reference.status_code == 200
        assert migrated.json() == reference.json()
        assert migrated.headers["last-modified"] == reference.headers["last-modified"]
        assert migrated.headers["cache-control"] == reference.headers["cache-control"]
    deleted = django_units_client.delete(path, headers=unique_user.token)
    assert deleted.status_code == 200
    assert deleted.json() == migrated.json()
    assert django_units_client.get(path, headers=unique_user.token).status_code == 404


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"page": 1, "perPage": 1},
        {"page": 2, "perPage": 1},
        {"page": -1, "perPage": 1},
        {"perPage": -1},
        {"perPage": 0},
        {"page": 0},
        {"per_page": 1},
        {"search": "alias"},
        {"orderBy": "name", "orderDirection": "asc", "perPage": 1},
        {"queryFilter": 'name = "not-present"'},
    ],
)
def test_pagination_parity(
    params: dict,
    django_units_client: TestClient,
    fastapi_units_client: TestClient,
    unique_user: TestUser,
    drf_unit: dict,
) -> None:
    django_units_client.post("/api/units", json={"name": random_string()}, headers=unique_user.token)
    migrated = django_units_client.get("/api/units", params=params, headers=unique_user.token)
    reference = fastapi_units_client.get("/api/units", params=params, headers=unique_user.token)
    assert migrated.status_code == reference.status_code == 200
    assert migrated.json() == reference.json()
    assert set(migrated.json()) == {"page", "per_page", "total", "total_pages", "items", "next", "previous"}


@pytest.mark.parametrize(
    "method,path,payload,expected",
    [
        ("get", "/api/units/missing", None, 422),
        ("get", f"/api/units/{uuid1()}", None, 422),
        ("get", f"/api/units/{uuid4()}", None, 404),
        ("put", f"/api/units/{uuid4()}", {"name": "missing"}, 404),
        ("delete", f"/api/units/{uuid4()}", None, 404),
        ("post", "/api/units", {}, 422),
        ("post", "/api/units", {"name": 123}, 422),
        ("post", "/api/units", {"name": "bad", "aliases": [{}]}, 422),
        ("post", "/api/units", {"name": "bad", "fraction": "invalid"}, 422),
        ("put", "/api/units/merge", {"fromUnit": str(uuid1()), "toUnit": str(uuid4())}, 422),
        ("get", "/api/units/merge", None, 422),
    ],
)
def test_error_parity(
    method: str,
    path: str,
    payload: dict | None,
    expected: int,
    django_units_client: TestClient,
    fastapi_units_client: TestClient,
    unique_user: TestUser,
    production_validation: None,
) -> None:
    migrated = django_units_client.request(method, path, json=payload, headers=unique_user.token)
    reference = fastapi_units_client.request(method, path, json=payload, headers=unique_user.token)
    assert migrated.status_code == reference.status_code == expected
    assert migrated.json() == reference.json()


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_authentication_parity(
    headers: dict, django_units_client: TestClient, fastapi_units_client: TestClient
) -> None:
    migrated = django_units_client.get("/api/units", headers=headers)
    reference = fastapi_units_client.get("/api/units", headers=headers)
    assert migrated.status_code == reference.status_code == 401
    assert migrated.json() == reference.json()
    assert migrated.headers["www-authenticate"] == reference.headers["www-authenticate"]


def test_group_isolation(
    django_units_client: TestClient, unique_user: TestUser, g2_user: TestUser, drf_unit: dict
) -> None:
    path = f"/api/units/{drf_unit['id']}"
    for method, payload in [("get", None), ("put", {"name": "forbidden"}), ("delete", None)]:
        assert django_units_client.request(method, path, headers=g2_user.token, json=payload).status_code == 404
    listing = django_units_client.get("/api/units", headers=g2_user.token).json()
    assert drf_unit["id"] not in [unit["id"] for unit in listing["items"]]
    assert django_units_client.get(path, headers=unique_user.token).status_code == 200


def test_units_are_shared_within_a_group(django_units_client: TestClient, h2_user: TestUser, drf_unit: dict) -> None:
    assert django_units_client.get(f"/api/units/{drf_unit['id']}", headers=h2_user.token).status_code == 200


def test_merge_and_missing_merge(django_units_client: TestClient, unique_user: TestUser, drf_unit: dict) -> None:
    target = django_units_client.post("/api/units", json={"name": random_string()}, headers=unique_user.token).json()
    source_model = unique_user.repos.ingredient_units.get_one(drf_unit["id"])
    recipe = unique_user.repos.recipes.create(
        Recipe(
            name=random_string(),
            user_id=unique_user.user_id,
            group_id=unique_user._group_id,
            recipe_ingredient=[RecipeIngredient(note="", unit=source_model)],
        )
    )
    merged = django_units_client.put(
        "/api/units/merge",
        headers=unique_user.token,
        json={
            "fromUnit": drf_unit["id"],
            "toUnit": target["id"],
        },
    )
    assert merged.status_code == 200
    assert merged.json() == {"message": "Successfully merged units", "error": False}
    assert django_units_client.get(f"/api/units/{drf_unit['id']}", headers=unique_user.token).status_code == 404
    unique_user.repos.session.expire_all()
    assert str(unique_user.repos.recipes.get_one(recipe.slug).recipe_ingredient[0].unit.id) == target["id"]
    failed = django_units_client.put(
        "/api/units/merge",
        headers=unique_user.token,
        json={
            "fromUnit": str(uuid4()),
            "toUnit": target["id"],
        },
    )
    assert failed.status_code == 500
    assert failed.json() == {"detail": "Failed to merge units"}


def test_serializers_and_no_django_models() -> None:
    from rest_framework.serializers import ModelSerializer, Serializer

    assert issubclass(UnitInputSerializer, Serializer)
    assert not issubclass(UnitInputSerializer, ModelSerializer)
    assert not issubclass(UnitSerializer, ModelSerializer)
    assert resolve("/api/units").func.view_class.__module__ == "mealie_drf.units.views"


def test_malformed_json_parity(
    django_units_client: TestClient,
    fastapi_units_client: TestClient,
    unique_user: TestUser,
    production_validation: None,
) -> None:
    migrated = django_units_client.post(
        "/api/units",
        content='{ "name": ',
        headers={
            **unique_user.token,
            "Content-Type": "application/json",
        },
    )
    reference = fastapi_units_client.post(
        "/api/units",
        content='{ "name": ',
        headers={
            **unique_user.token,
            "Content-Type": "application/json",
        },
    )
    assert migrated.status_code == reference.status_code == 422
    assert migrated.json() == reference.json()


@pytest.mark.parametrize("path", ["/api/units/missing", f"/api/units/{uuid1()}"])
def test_debug_validation_parity(
    path: str, django_units_client: TestClient, fastapi_units_client: TestClient, unique_user: TestUser
) -> None:
    migrated = django_units_client.get(path, headers=unique_user.token).json()
    reference = fastapi_units_client.get(path, headers=unique_user.token).json()
    assert set(migrated) == set(reference) == {"status_code", "message", "data"}
    assert migrated["status_code"] == reference["status_code"] == 422
    assert migrated["data"] is reference["data"] is None
    # Source diagnostics must identify the migrated implementation, while every
    # validation detail before those diagnostics stays identical.
    assert migrated["message"].split(" File ")[0] == reference["message"].split(" File ")[0]
    assert "mealie_drf/units/views.py" in migrated["message"]
    assert f"GET {path}" in migrated["message"]


@pytest.mark.parametrize("path", ["/api/units/", "/api/units/missing/", "/api/units/merge/"])
def test_trailing_slash_parity(path: str, django_units_client: TestClient, fastapi_units_client: TestClient) -> None:
    migrated = django_units_client.get(path, params={"perPage": 1}, follow_redirects=False)
    reference = fastapi_units_client.get(path, params={"perPage": 1}, follow_redirects=False)
    assert migrated.status_code == reference.status_code == 307
    assert migrated.headers["location"] == reference.headers["location"]


def test_unknown_child_path_parity(django_units_client: TestClient, fastapi_units_client: TestClient) -> None:
    migrated = django_units_client.get("/api/units/missing/child")
    reference = fastapi_units_client.get("/api/units/missing/child")
    assert migrated.status_code == reference.status_code == 404
    assert migrated.json() == reference.json() == {"detail": "Not Found"}


def test_duplicate_conflict_parity(
    django_units_client: TestClient, fastapi_units_client: TestClient, unique_user: TestUser, drf_unit: dict
) -> None:
    for client in [django_units_client, fastapi_units_client]:
        failed = client.post("/api/units", json={"name": drf_unit["name"]}, headers=unique_user.token)
        assert failed.status_code == 409
        detail = failed.json()["detail"]
        assert set(detail) == {"message", "error", "exception"}
        assert detail["message"] == "This item already exists."
        assert detail["error"] is True
        assert isinstance(detail["exception"], str) and detail["exception"]
        assert client.get(f"/api/units/{drf_unit['id']}", headers=unique_user.token).status_code == 200


@pytest.mark.parametrize("language,expected_unit,expected_quantity", [("de-DE", "cup", 1), ("en-US", None, None)])
def test_locale_standardization_parity(
    language: str,
    expected_unit: str | None,
    expected_quantity: int | None,
    django_units_client: TestClient,
    fastapi_units_client: TestClient,
    unique_user: TestUser,
) -> None:
    for client in [django_units_client, fastapi_units_client]:
        response = client.post(
            "/api/units",
            json={"name": random_string(), "pluralName": "Tasse"},
            headers={**unique_user.token, "Accept-Language": language},
        )
        assert response.status_code == 201
        assert response.json()["standardUnit"] == expected_unit
        assert response.json()["standardQuantity"] == expected_quantity


def test_dispatcher_routes_units_and_foods(monkeypatch: pytest.MonkeyPatch, unique_user: TestUser) -> None:
    calls: list[str] = []
    django_target = application.django_app
    fastapi_target = application.fastapi_app

    async def django_probe(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append("django")
        await django_target(scope, receive, send)

    async def fastapi_probe(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append("fastapi")
        await fastapi_target(scope, receive, send)

    monkeypatch.setattr(application, "django_app", django_probe)
    monkeypatch.setattr(application, "fastapi_app", fastapi_probe)
    client = TestClient(application)
    for path, target in [
        ("/api/units", "django"),
        (f"/api/units/{uuid4()}", "django"),
        ("/api/units/merge", "django"),
        ("/api/foods", "django"),
        ("/api/organizers/tags", "fastapi"),
        ("/api/users/self", "fastapi"),
        ("/api/recipes", "fastapi"),
        ("/api/units-extra", "fastapi"),
    ]:
        calls.clear()
        client.get(path, headers=unique_user.token)
        assert calls == [target]


def test_malformed_json_before_authentication(
    django_units_client: TestClient, fastapi_units_client: TestClient, production_validation: None
) -> None:
    for client in [django_units_client, fastapi_units_client]:
        response = client.post("/api/units", content="{", headers={"Content-Type": "application/json"})
        assert response.status_code == 422
        assert response.json() == {
            "detail": [
                {
                    "type": "json_invalid",
                    "loc": ["body", 1],
                    "msg": "JSON decode error",
                    "input": {},
                    "ctx": {"error": "Expecting property name enclosed in double quotes"},
                }
            ]
        }


@pytest.mark.parametrize("method", ["put", "delete"])
def test_unsupported_method_parity(
    method: str, django_units_client: TestClient, fastapi_units_client: TestClient
) -> None:
    migrated = django_units_client.request(method, "/api/units")
    reference = fastapi_units_client.request(method, "/api/units")
    assert migrated.status_code == reference.status_code == 405
    assert migrated.json() == reference.json() == {"detail": "Method Not Allowed"}
