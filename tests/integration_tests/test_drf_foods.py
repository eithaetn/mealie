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

from mealie_drf.foods.serializers import FoodInputSerializer, FoodSerializer


@pytest.fixture
def django_foods_client() -> TestClient:
    return TestClient(django_app)


@pytest.fixture
def fastapi_foods_client() -> TestClient:
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
def drf_food(django_foods_client: TestClient, unique_user: TestUser) -> dict:
    response = django_foods_client.post(
        "/api/foods",
        headers=unique_user.token,
        json={
            "name": random_string(),
            "pluralName": "plural",
            "description": None,
            "aliases": [{"name": "alias"}],
            "extras": {"source": "market"},
        },
    )
    assert response.status_code == 201
    return response.json()


def test_drf_crud_and_output_parity(
    django_foods_client: TestClient, fastapi_foods_client: TestClient, unique_user: TestUser, drf_food: dict
) -> None:
    path = f"/api/foods/{drf_food['id']}"
    for payload in [None, {"name": random_string(), "aliases": [], "extras": None}]:
        if payload is not None:
            updated = django_foods_client.put(path, json=payload, headers=unique_user.token)
            assert updated.status_code == 200
        migrated = django_foods_client.get(path, headers=unique_user.token)
        reference = fastapi_foods_client.get(path, headers=unique_user.token)
        assert migrated.status_code == reference.status_code == 200
        assert migrated.json() == reference.json()
        assert migrated.headers["last-modified"] == reference.headers["last-modified"]
        assert migrated.headers["cache-control"] == reference.headers["cache-control"]
    deleted = django_foods_client.delete(path, headers=unique_user.token)
    assert deleted.status_code == 200
    assert deleted.json() == migrated.json()
    assert django_foods_client.get(path, headers=unique_user.token).status_code == 404


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
    django_foods_client: TestClient,
    fastapi_foods_client: TestClient,
    unique_user: TestUser,
    drf_food: dict,
) -> None:
    django_foods_client.post("/api/foods", json={"name": random_string()}, headers=unique_user.token)
    migrated = django_foods_client.get("/api/foods", params=params, headers=unique_user.token)
    reference = fastapi_foods_client.get("/api/foods", params=params, headers=unique_user.token)
    assert migrated.status_code == reference.status_code == 200
    assert migrated.json() == reference.json()
    assert set(migrated.json()) == {"page", "per_page", "total", "total_pages", "items", "next", "previous"}


@pytest.mark.parametrize(
    "method,path,payload,expected",
    [
        ("get", "/api/foods/missing", None, 422),
        ("get", f"/api/foods/{uuid1()}", None, 422),
        ("get", f"/api/foods/{uuid4()}", None, 404),
        ("put", f"/api/foods/{uuid4()}", {"name": "missing"}, 404),
        ("delete", f"/api/foods/{uuid4()}", None, 404),
        ("post", "/api/foods", {}, 422),
        ("post", "/api/foods", {"name": 123}, 422),
        ("post", "/api/foods", {"name": "bad", "aliases": [{}]}, 422),
        ("post", "/api/foods", {"name": "bad", "labelId": "invalid"}, 422),
        ("put", "/api/foods/merge", {"fromFood": str(uuid1()), "toFood": str(uuid4())}, 422),
        ("get", "/api/foods/merge", None, 422),
    ],
)
def test_error_parity(
    method: str,
    path: str,
    payload: dict | None,
    expected: int,
    django_foods_client: TestClient,
    fastapi_foods_client: TestClient,
    unique_user: TestUser,
    production_validation: None,
) -> None:
    migrated = django_foods_client.request(method, path, json=payload, headers=unique_user.token)
    reference = fastapi_foods_client.request(method, path, json=payload, headers=unique_user.token)
    assert migrated.status_code == reference.status_code == expected
    assert migrated.json() == reference.json()


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_authentication_parity(
    headers: dict, django_foods_client: TestClient, fastapi_foods_client: TestClient
) -> None:
    migrated = django_foods_client.get("/api/foods", headers=headers)
    reference = fastapi_foods_client.get("/api/foods", headers=headers)
    assert migrated.status_code == reference.status_code == 401
    assert migrated.json() == reference.json()
    assert migrated.headers["www-authenticate"] == reference.headers["www-authenticate"]


def test_group_isolation(
    django_foods_client: TestClient,
    fastapi_foods_client: TestClient,
    unique_user: TestUser,
    g2_user: TestUser,
    drf_food: dict,
) -> None:
    user = g2_user.repos.users.get_one(g2_user.user_id)
    original = user.can_organize
    user.can_organize = True
    g2_user.repos.users.update(user.id, user)
    try:
        path = f"/api/foods/{drf_food['id']}"
        for client in [django_foods_client, fastapi_foods_client]:
            for method, payload in [("get", None), ("put", {"name": "forbidden"}), ("delete", None)]:
                assert client.request(method, path, headers=g2_user.token, json=payload).status_code == 404
            listing = client.get("/api/foods", headers=g2_user.token).json()
            assert drf_food["id"] not in [food["id"] for food in listing["items"]]
        assert django_foods_client.get(path, headers=unique_user.token).status_code == 200
    finally:
        user.can_organize = original
        g2_user.repos.users.update(user.id, user)


def test_foods_are_shared_within_a_group(django_foods_client: TestClient, h2_user: TestUser, drf_food: dict) -> None:
    assert django_foods_client.get(f"/api/foods/{drf_food['id']}", headers=h2_user.token).status_code == 200


def test_merge_and_missing_merge(django_foods_client: TestClient, unique_user: TestUser, drf_food: dict) -> None:
    target = django_foods_client.post("/api/foods", json={"name": random_string()}, headers=unique_user.token).json()
    source_model = unique_user.repos.ingredient_foods.get_one(drf_food["id"])
    recipe = unique_user.repos.recipes.create(
        Recipe(
            name=random_string(),
            user_id=unique_user.user_id,
            group_id=unique_user._group_id,
            recipe_ingredient=[RecipeIngredient(note="", food=source_model)],
        )
    )
    merged = django_foods_client.put(
        "/api/foods/merge",
        headers=unique_user.token,
        json={
            "fromFood": drf_food["id"],
            "toFood": target["id"],
        },
    )
    assert merged.status_code == 200
    assert merged.json() == {"message": "Successfully merged foods", "error": False}
    assert django_foods_client.get(f"/api/foods/{drf_food['id']}", headers=unique_user.token).status_code == 404
    unique_user.repos.session.expire_all()
    assert str(unique_user.repos.recipes.get_one(recipe.slug).recipe_ingredient[0].food.id) == target["id"]
    failed = django_foods_client.put(
        "/api/foods/merge",
        headers=unique_user.token,
        json={
            "fromFood": str(uuid4()),
            "toFood": target["id"],
        },
    )
    assert failed.status_code == 500
    assert failed.json() == {"detail": "Failed to merge foods"}


def test_serializers_and_no_django_models() -> None:
    from rest_framework.serializers import ModelSerializer, Serializer

    assert issubclass(FoodInputSerializer, Serializer)
    assert not issubclass(FoodInputSerializer, ModelSerializer)
    assert not issubclass(FoodSerializer, ModelSerializer)
    assert resolve("/api/foods").func.view_class.__module__ == "mealie_drf.foods.views"


def test_malformed_json_parity(
    django_foods_client: TestClient,
    fastapi_foods_client: TestClient,
    unique_user: TestUser,
    production_validation: None,
) -> None:
    migrated = django_foods_client.post(
        "/api/foods",
        content='{ "name": ',
        headers={
            **unique_user.token,
            "Content-Type": "application/json",
        },
    )
    reference = fastapi_foods_client.post(
        "/api/foods",
        content='{ "name": ',
        headers={
            **unique_user.token,
            "Content-Type": "application/json",
        },
    )
    assert migrated.status_code == reference.status_code == 422
    assert migrated.json() == reference.json()


@pytest.mark.parametrize("path", ["/api/foods/missing", f"/api/foods/{uuid1()}"])
def test_debug_validation_parity(
    path: str, django_foods_client: TestClient, fastapi_foods_client: TestClient, unique_user: TestUser
) -> None:
    migrated = django_foods_client.get(path, headers=unique_user.token).json()
    reference = fastapi_foods_client.get(path, headers=unique_user.token).json()
    assert set(migrated) == set(reference) == {"status_code", "message", "data"}
    assert migrated["status_code"] == reference["status_code"] == 422
    assert migrated["data"] is reference["data"] is None
    # Source diagnostics must identify the migrated implementation, while every
    # validation detail before those diagnostics stays identical.
    assert migrated["message"].split(" File ")[0] == reference["message"].split(" File ")[0]
    assert "mealie_drf/foods/views.py" in migrated["message"]
    assert f"GET {path}" in migrated["message"]


@pytest.mark.parametrize("path", ["/api/foods/", "/api/foods/missing/", "/api/foods/merge/"])
def test_trailing_slash_parity(path: str, django_foods_client: TestClient, fastapi_foods_client: TestClient) -> None:
    migrated = django_foods_client.get(path, params={"perPage": 1}, follow_redirects=False)
    reference = fastapi_foods_client.get(path, params={"perPage": 1}, follow_redirects=False)
    assert migrated.status_code == reference.status_code == 307
    assert migrated.headers["location"] == reference.headers["location"]


def test_unknown_child_path_parity(django_foods_client: TestClient, fastapi_foods_client: TestClient) -> None:
    migrated = django_foods_client.get("/api/foods/missing/child")
    reference = fastapi_foods_client.get("/api/foods/missing/child")
    assert migrated.status_code == reference.status_code == 404
    assert migrated.json() == reference.json() == {"detail": "Not Found"}


def test_duplicate_conflict_parity(
    django_foods_client: TestClient, fastapi_foods_client: TestClient, unique_user: TestUser, drf_food: dict
) -> None:
    for client in [django_foods_client, fastapi_foods_client]:
        failed = client.post("/api/foods", json={"name": drf_food["name"]}, headers=unique_user.token)
        assert failed.status_code == 409
        detail = failed.json()["detail"]
        assert set(detail) == {"message", "error", "exception"}
        assert detail["message"] == "This item already exists."
        assert detail["error"] is True
        assert isinstance(detail["exception"], str) and detail["exception"]
        assert client.get(f"/api/foods/{drf_food['id']}", headers=unique_user.token).status_code == 200


def test_malformed_json_before_authentication(
    django_foods_client: TestClient, fastapi_foods_client: TestClient, production_validation: None
) -> None:
    for client in [django_foods_client, fastapi_foods_client]:
        response = client.post("/api/foods", content="{", headers={"Content-Type": "application/json"})
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
    method: str, django_foods_client: TestClient, fastapi_foods_client: TestClient
) -> None:
    migrated = django_foods_client.request(method, "/api/foods")
    reference = fastapi_foods_client.request(method, "/api/foods")
    assert migrated.status_code == reference.status_code == 405
    assert migrated.json() == reference.json() == {"detail": "Method Not Allowed"}


def test_food_organizer_permissions(
    django_foods_client: TestClient,
    fastapi_foods_client: TestClient,
    unique_user: TestUser,
    drf_food: dict,
    production_validation: None,
) -> None:
    user = unique_user.repos.users.get_one(unique_user.user_id)
    original = user.can_organize
    user.can_organize = False
    unique_user.repos.users.update(user.id, user)
    try:
        for client in [django_foods_client, fastapi_foods_client]:
            assert client.get("/api/foods", headers=unique_user.token).status_code == 200
            assert client.get(f"/api/foods/{drf_food['id']}", headers=unique_user.token).status_code == 200
            for method, path, payload in [
                ("post", "/api/foods", {"name": random_string()}),
                ("put", f"/api/foods/{drf_food['id']}", {"name": "denied"}),
                ("delete", f"/api/foods/{drf_food['id']}", None),
                ("put", "/api/foods/merge", {"fromFood": drf_food["id"], "toFood": str(uuid4())}),
            ]:
                response = client.request(method, path, json=payload, headers=unique_user.token)
                assert response.status_code == 403
                assert response.json() == {"detail": "Forbidden"}
            assert client.post("/api/foods", json={}, headers=unique_user.token).status_code == 422
    finally:
        user.can_organize = original
        unique_user.repos.users.update(user.id, user)


def test_food_substitution_normalization(
    django_foods_client: TestClient,
    fastapi_foods_client: TestClient,
    unique_user: TestUser,
) -> None:
    for client in [django_foods_client, fastapi_foods_client]:
        response = client.post(
            "/api/foods",
            headers=unique_user.token,
            json={
                "name": random_string(),
                "description": None,
                "id": "",
                "substitutions": [{}, {"note": "  broth  "}, {"note": "  "}],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["description"] == ""
        assert data["substitutions"] == [{"substituteFoodId": None, "note": "broth", "substituteFood": None}]


def test_nested_extras_preserves_repository_bad_request(
    django_foods_client: TestClient,
    fastapi_foods_client: TestClient,
    unique_user: TestUser,
) -> None:
    for client in [django_foods_client, fastapi_foods_client]:
        response = client.post(
            "/api/foods", headers=unique_user.token, json={"name": random_string(), "extras": {"nested": {"value": 3}}}
        )
        assert response.status_code == 400
        assert response.json()["detail"]["error"] is True


@pytest.mark.parametrize("language", ["de-DE", "en-US"])
def test_localized_conflict_parity(
    language: str,
    django_foods_client: TestClient,
    fastapi_foods_client: TestClient,
    unique_user: TestUser,
    drf_food: dict,
) -> None:
    responses = [
        client.post(
            "/api/foods", json={"name": drf_food["name"]}, headers={**unique_user.token, "Accept-Language": language}
        )
        for client in [django_foods_client, fastapi_foods_client]
    ]
    assert all(response.status_code == 409 for response in responses)
    assert responses[0].json()["detail"]["message"] == responses[1].json()["detail"]["message"]


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
        (f"/api/foods/{uuid4()}", "django"),
        ("/api/foods/merge", "django"),
        ("/api/foods-extra", "fastapi"),
        ("/api/organizers/tags", "django"),
        ("/api/organizers/categories", "fastapi"),
        ("/api/organizers/tools", "fastapi"),
        ("/api/users/self", "fastapi"),
        ("/api/recipes", "fastapi"),
        ("/api/units-extra", "fastapi"),
    ]:
        calls.clear()
        client.get(path, headers=unique_user.token)
        assert calls == [target]
