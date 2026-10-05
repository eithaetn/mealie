import pytest
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from mealie_drf.dispatcher import ASGIDispatcher


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope_type", "path", "root_path", "ported_prefixes", "expected"),
    [
        ("http", "/api/foods", "", (), "fastapi"),
        ("http", "/api/foods", "", ("/api/foods",), "django"),
        ("http", "/api/foods/123", "", ("/api/foods",), "django"),
        ("http", "/api/foods-other", "", ("/api/foods",), "fastapi"),
        ("http", "/api/foods/123", "", ("/api/foods/",), "django"),
        ("http", "/api/users", "", ("/api/foods",), "fastapi"),
        ("http", "/_drf/health/", "", (), "django"),
        ("http", "/_drf/health/extra", "", (), "fastapi"),
        ("http", "/mount/_drf/health/", "/mount", (), "django"),
        ("websocket", "/_drf/health/", "", (), "fastapi"),
        ("websocket", "/api/foods", "", ("/api/foods",), "fastapi"),
        ("lifespan", "", "", (), "fastapi"),
    ],
)
async def test_dispatch_routing(
    scope_type: str, path: str, root_path: str, ported_prefixes: tuple[str, ...], expected: str
) -> None:
    calls: list[str] = []
    scope: Scope = {"type": scope_type, "path": path, "root_path": root_path}

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        pass

    async def fastapi_app(actual_scope: Scope, actual_receive: Receive, actual_send: Send) -> None:
        assert actual_scope is scope
        assert actual_receive is receive
        assert actual_send is send
        calls.append("fastapi")

    async def django_app(actual_scope: Scope, actual_receive: Receive, actual_send: Send) -> None:
        assert actual_scope is scope
        assert actual_receive is receive
        assert actual_send is send
        calls.append("django")

    dispatcher = ASGIDispatcher(
        fastapi_app, django_app, ported_prefixes=ported_prefixes, infrastructure_paths=("/_drf/health/",)
    )
    await dispatcher(scope, receive, send)
    assert calls == [expected]


def test_drf_health() -> None:
    from django.conf import settings

    from mealie_drf.asgi import PORTED_HTTP_PREFIXES, application

    response = TestClient(application).get("/_drf/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"] == "application/json"
    assert PORTED_HTTP_PREFIXES == ("/api/units", "/api/foods")
    assert "django.contrib.auth" not in settings.INSTALLED_APPS
    assert "django.contrib.sessions" not in settings.INSTALLED_APPS
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.dummy"
