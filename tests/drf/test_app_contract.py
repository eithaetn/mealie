from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import Depends, FastAPI, Response
from sqlalchemy.orm import Session

from mealie.db.db_setup import generate_session
from mealie.drf.asgi import application  # noqa: F401 - configure Django before importing DRF views
from mealie.drf.dispatch import DjangoAPIMiddleware
from mealie.schema.admin.about import AppInfo, AppStartupInfo, AppTheme
from mealie.services.app_info_service import AppInfoService


@pytest.fixture
def applications(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, FastAPI, MagicMock]:
    session = MagicMock()

    @contextmanager
    def session_context() -> Iterator[MagicMock]:
        try:
            yield session
        finally:
            session.close()

    repos = MagicMock()
    repos.groups.get_by_name.return_value = None
    repos.users.count_all.return_value = 1
    monkeypatch.setattr("mealie.services.app_info_service.get_repositories", lambda *args, **kwargs: repos)
    monkeypatch.setattr("mealie.drf.views.session_context", session_context)

    # Standalone reference declarations preserve the old FastAPI serialization
    # and method handling without importing the full legacy route tree (LDAP).
    legacy = FastAPI()

    @legacy.get("/api/app/about", response_model=AppInfo)
    def info(db: Session = Depends(generate_session)) -> AppInfo:
        return AppInfoService().get_info(db)

    @legacy.get("/api/app/about/startup-info", response_model=AppStartupInfo)
    def startup(db: Session = Depends(generate_session)) -> AppStartupInfo:
        return AppInfoService().get_startup_info(db)

    @legacy.get("/api/app/about/theme", response_model=AppTheme)
    def theme(response: Response) -> AppTheme:
        response.headers["Cache-Control"] = "public, max-age=604800"
        return AppInfoService().get_theme()

    legacy.dependency_overrides[generate_session] = lambda: session
    migrated = FastAPI()
    migrated.router.routes = list(legacy.router.routes)
    migrated.add_middleware(DjangoAPIMiddleware)
    return legacy, migrated, session


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/app/about", "/api/app/about/startup-info", "/api/app/about/theme"])
@pytest.mark.parametrize("accept", ["application/json", "text/html", "application/xml"])
async def test_response_contract(applications: tuple, path: str, accept: str) -> None:
    legacy, migrated, session = applications
    responses = []
    for app in [legacy, migrated]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            responses.append(await client.get(path, headers={"Accept": accept}))
    before, after = responses
    assert after.status_code == before.status_code == 200
    assert after.json() == before.json()
    assert after.headers["content-type"] == before.headers["content-type"]
    assert after.headers.get("cache-control") == before.headers.get("cache-control")
    if not path.endswith("theme"):
        session.close.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def test_method_contract(applications: tuple, method: str) -> None:
    legacy, migrated, _ = applications
    responses = []
    for app in [legacy, migrated]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            responses.append(await client.request(method, "/api/app/about/theme"))
    before, after = responses
    assert after.status_code == before.status_code == 405
    assert after.content == before.content
    assert after.headers["allow"] == before.headers["allow"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/app/about/theme/", "/api/app/missing", "/openapi.json"])
async def test_legacy_fallback(applications: tuple, path: str) -> None:
    legacy, migrated, _ = applications
    responses = []
    for app in [legacy, migrated]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            responses.append(await client.get(path))
    before, after = responses
    assert after.status_code == before.status_code
    assert after.content == before.content
    assert after.headers.get("location") == before.headers.get("location")


@pytest.mark.asyncio
async def test_converted_endpoint_does_not_call_legacy_handler(applications: tuple) -> None:
    _, migrated, _ = applications
    # If dispatch accidentally falls through, there is no legacy route to answer.
    migrated.router.routes.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=migrated), base_url="http://test") as client:
        response = await client.get("/api/app/about/theme")
    assert response.status_code == 200
    assert "lightPrimary" in response.json()


@pytest.mark.asyncio
async def test_database_session_closed_on_error(applications: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    _, migrated, session = applications

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("mealie.services.app_info_service.AppInfoService.get_info", fail)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=migrated), base_url="http://test") as client:
        response = await client.get("/api/app/about")
    assert response.status_code == 500
    session.close.assert_called_once()


@pytest.mark.asyncio
async def test_proxy_root_path(applications: tuple) -> None:
    _, migrated, _ = applications
    transport = httpx.ASGITransport(app=migrated, root_path="/mealie")
    async with httpx.AsyncClient(transport=transport, base_url="http://test/mealie") as client:
        response = await client.get("/api/app/about/theme")
    assert response.status_code == 200
    assert "lightPrimary" in response.json()
