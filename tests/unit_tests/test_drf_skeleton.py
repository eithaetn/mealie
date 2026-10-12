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
    assert PORTED_HTTP_PREFIXES == ("/api/units", "/api/foods", "/api/organizers/tags")
    assert "django.contrib.auth" not in settings.INSTALLED_APPS
    assert "django.contrib.sessions" not in settings.INSTALLED_APPS
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.dummy"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/organizers/tags", "/api/foods"])
async def test_tag_response_middleware_is_scoped(path: str) -> None:
    import gzip

    from starlette.datastructures import Headers

    from mealie_drf.tags.middleware import TagHTTPMiddleware

    payload = b'{"value":"' + b"x" * 80000 + b'"}'
    messages: list[dict] = []

    async def source(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": payload[:40000], "more_body": True})
        await send({"type": "http.response.body", "body": payload[40000:]})

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    await TagHTTPMiddleware(source)(
        {"type": "http", "path": path, "headers": [(b"accept-encoding", b"gzip")]}, receive, send
    )
    headers = Headers(raw=messages[0]["headers"])
    if path == "/api/organizers/tags":
        assert len(messages) == 2
        assert headers["content-encoding"] == "gzip"
        assert int(headers["content-length"]) == len(messages[1]["body"])
        assert gzip.decompress(messages[1]["body"]) == payload
    else:
        assert len(messages) == 3
        assert "content-encoding" not in headers
        assert "content-length" not in headers


@pytest.mark.asyncio
async def test_registered_route_dispatch_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.routing import _iter_routes_with_context

    from mealie.app import app as fastapi_app
    from mealie_drf.asgi import PORTED_HTTP_PREFIXES, application

    calls: list[str] = []

    async def fastapi_probe(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append("fastapi")

    async def django_probe(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append("django")

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        pass

    monkeypatch.setattr(application, "fastapi_app", fastapi_probe)
    monkeypatch.setattr(application, "django_app", django_probe)
    paths = [
        context.path if context is not None else route.path
        for route, context in _iter_routes_with_context(fastapi_app.routes)
    ]
    paths += ["/api/organizers/tags-other", "/api/organizers/tags/missing/child"]
    for root_path in ["", "/mount"]:
        for path in paths:
            expected = (
                "django"
                if any(path == prefix or path.startswith(prefix + "/") for prefix in PORTED_HTTP_PREFIXES)
                else "fastapi"
            )
            calls.clear()
            await application({"type": "http", "path": root_path + path, "root_path": root_path}, receive, send)
            assert calls == [expected], path
    for scope_type in ["websocket", "lifespan"]:
        calls.clear()
        await application({"type": scope_type, "path": "/api/organizers/tags"}, receive, send)
        assert calls == ["fastapi"]
