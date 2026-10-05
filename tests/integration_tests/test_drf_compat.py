import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session
from starlette.requests import Request as StarletteRequest

from mealie.app import app as fastapi_app
from mealie.core.config import get_app_settings
from mealie.core.security.tokens import ALGORITHM, create_access_token
from mealie.db import db_setup
from mealie.schema.response import ErrorResponse

# isort: split
# Initialize Django before DRF reads its settings. Probe URLs exist only under override_settings.
from mealie_drf.asgi import django_app

# isort: split
from django.test import override_settings
from django.urls import path
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from mealie_drf.base import MealieAPIView
from mealie_drf.context import get_request_context, get_request_session
from mealie_drf.errors import bad_request, conflict, exception_handler, not_found, validate_input
from tests.utils import api_routes
from tests.utils.fixture_schemas import TestUser


class ContextProbe(MealieAPIView):
    def get(self, request: Request) -> Response:
        context = get_request_context(request)
        assert request.user is context.user
        context.session.info["view_thread"] = threading.get_ident()
        assert get_request_session(request) is context.session
        assert context.repos is context.repos
        assert context.repos.session is context.session
        assert context.repos.group_id == context.group_id
        assert context.repos.household_id == context.household_id
        assert context.repos.recipes.group_id == context.group_id
        assert context.repos.recipes.household_id == context.household_id
        assert context.repos.users.get_one(context.user.id).id == context.user.id
        return Response(
            {"id": str(context.user.id), "group_id": str(context.group_id), "household_id": str(context.household_id)}
        )


def probe(headers: dict[str, str] | None = None, cookie: str | None = None) -> Response:
    request = APIRequestFactory().get("/_test/context/", headers=headers or {})
    if cookie is not None:
        request.COOKIES["mealie.access_token"] = cookie
    return ContextProbe.as_view()(request)


@pytest.fixture
def tracked_sessions(monkeypatch: pytest.MonkeyPatch) -> list[Session]:
    sessions: list[Session] = []
    factory = db_setup.SessionLocal

    def create_session() -> Session:
        session = factory()
        session.info["created_thread"] = threading.get_ident()
        original_close = session.close

        def close() -> None:
            session.info["closed_thread"] = threading.get_ident()
            original_close()

        session.close = Mock(side_effect=close)
        session.commit = Mock(wraps=session.commit)
        session.rollback = Mock(wraps=session.rollback)
        sessions.append(session)
        return session

    monkeypatch.setattr(db_setup, "SessionLocal", create_session)
    return sessions


def test_bearer_user_context(unique_user: TestUser, tracked_sessions: list[Session]) -> None:
    response = probe(unique_user.token)
    assert response.status_code == 200
    assert response.data == {
        "id": str(unique_user.user_id),
        "group_id": unique_user.group_id,
        "household_id": unique_user.household_id,
    }
    assert len(tracked_sessions) == 1
    tracked_sessions[0].close.assert_called_once()
    # The existing auth helper commits its read transaction; the wrapper adds no commit.
    tracked_sessions[0].commit.assert_called_once()


def test_repository_context_does_not_expose_other_groups(unique_user: TestUser, g2_user: TestUser) -> None:
    class ScopeProbe(ContextProbe):
        def get(self, request: Request) -> Response:
            context = get_request_context(request)
            assert context.repos.users.get_one(g2_user.user_id) is None
            return super().get(request)

    request = APIRequestFactory().get("/_test/scope/", headers=unique_user.token)
    assert ScopeProbe.as_view()(request).status_code == 200


def test_django_asgi_authentication(unique_user: TestUser, tracked_sessions: list[Session]) -> None:
    test_urls = ModuleType("drf_compat_probe_urls")
    test_urls.urlpatterns = [path("_test/context/", ContextProbe.as_view())]
    with override_settings(ROOT_URLCONF=test_urls):
        response = TestClient(django_app).get("/_test/context/", headers=unique_user.token)
    assert response.status_code == 200
    assert response.json()["id"] == str(unique_user.user_id)
    session = tracked_sessions[0]
    assert session.info["created_thread"] == session.info["view_thread"] == session.info["closed_thread"]
    session.close.assert_called_once()


def test_health_does_not_open_session(tracked_sessions: list[Session]) -> None:
    response = TestClient(django_app).get("/_drf/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert tracked_sessions == []


@pytest.mark.parametrize("mode", ["missing", "invalid", "expired", "wrong-signature", "no-sub", "unknown-user"])
def test_authentication_failure(mode: str, tracked_sessions: list[Session]) -> None:
    token = "not-a-token"
    if mode == "expired":
        token, _ = create_access_token({"sub": str(uuid4())}, expires_delta=timedelta(seconds=-1))
    elif mode == "wrong-signature":
        token = jwt.encode({"sub": str(uuid4())}, "a-different-secret-that-is-long-enough", algorithm=ALGORITHM)
    elif mode in {"no-sub", "unknown-user"}:
        token, _ = create_access_token({} if mode == "no-sub" else {"sub": str(uuid4())})
    response = probe(None if mode == "missing" else {"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.data == {"detail": "Could not validate credentials"}
    assert response["WWW-Authenticate"] == "Bearer"
    assert len(tracked_sessions) == 1
    tracked_sessions[0].close.assert_called_once()
    tracked_sessions[0].rollback.assert_called_once()


def test_cookie_fallback_and_header_precedence(unique_user: TestUser) -> None:
    token = unique_user.token["Authorization"].split(" ", 1)[1]
    assert probe(cookie=token).status_code == 200
    assert probe({"Authorization": "Basic ignored"}, cookie=token).status_code == 200
    assert probe({"Authorization": "Bearer invalid"}, cookie=token).status_code == 401
    assert probe({"Authorization": "Bearer "}, cookie=token).status_code == 401
    assert probe({"Authorization": f"bEaReR {token}"}).status_code == 200


def test_long_lived_token_and_revocation(api_client: TestClient, unique_user: TestUser) -> None:
    response = api_client.post(
        api_routes.users_api_tokens, json={"name": "DRF infrastructure"}, headers=unique_user.token
    )
    assert response.status_code == 201
    data = response.json()
    headers = {"Authorization": f"Bearer {data['token']}"}
    assert probe(headers).data["id"] == str(unique_user.user_id)
    response = api_client.delete(api_routes.users_api_tokens_token_id(data["id"]), headers=unique_user.token)
    assert response.status_code == 200
    rejected = probe(headers)
    assert rejected.status_code == 401
    assert rejected.data == {"detail": "Unauthorized"}


def test_password_token_cutoff(unique_user_fn_scoped: TestUser) -> None:
    user = unique_user_fn_scoped
    model = user.repos.users.get_one(user.user_id)
    model.tokens_valid_after = datetime.now(UTC) + timedelta(seconds=1)
    user.repos.users.update(user.user_id, model)
    assert probe(user.token).status_code == 401


@pytest.mark.parametrize("failure", [None, "handled", "unhandled", "render"])
def test_session_lifecycle(failure: str | None, tracked_sessions: list[Session]) -> None:
    thread_ids: list[int] = []

    class ProbeRenderer(JSONRenderer):
        def render(
            self, data: Any, accepted_media_type: str | None = None, renderer_context: dict | None = None
        ) -> bytes:
            thread_ids.append(threading.get_ident())
            tracked_sessions[-1].close.assert_not_called()
            if failure == "render":
                raise RuntimeError("render failed")
            return super().render(data, accepted_media_type, renderer_context)

    class SessionProbe(MealieAPIView):
        authentication_classes: list = []
        renderer_classes = [ProbeRenderer]

        def get(self, request: Request) -> Response:
            thread_ids.append(threading.get_ident())
            get_request_session(request).execute(text("SELECT 1"))
            if failure == "handled":
                raise bad_request("bad input")
            if failure == "unhandled":
                raise RuntimeError("view failed")
            return Response({"status": "ok"})

    request = APIRequestFactory().get("/_test/session/")
    for _ in range(2):
        if failure in {"unhandled", "render"}:
            with pytest.raises(RuntimeError):
                SessionProbe.as_view()(request)
        else:
            response = SessionProbe.as_view()(request)
            assert response.status_code == (400 if failure == "handled" else 200)
        tracked_sessions[-1].close.assert_called_once()
        tracked_sessions[-1].commit.assert_not_called()
        assert not tracked_sessions[-1].in_transaction()
        assert not hasattr(request, "mealie_session")
    assert len(tracked_sessions) == 2
    assert tracked_sessions[0] is not tracked_sessions[1]
    assert set(thread_ids) == {threading.get_ident()}


def test_uncommitted_writes_are_not_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE lifecycle_probe (value INTEGER)"))
    monkeypatch.setattr(db_setup, "SessionLocal", lambda: Session(engine))

    class WriteProbe(MealieAPIView):
        authentication_classes: list = []

        def post(self, request: Request) -> Response:
            get_request_session(request).execute(text("INSERT INTO lifecycle_probe VALUES (1)"))
            return Response({"status": "ok"})

    try:
        response = WriteProbe.as_view()(APIRequestFactory().post("/_test/write/"))
        assert response.status_code == 200
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM lifecycle_probe")).scalar_one() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (bad_request("bad input"), 400, "bad input"),
        (not_found(), 404, "Not Found"),
        (conflict(ErrorResponse.respond("already exists")), 409, ErrorResponse.respond("already exists")),
        (HTTPException(401, "invalid", headers={"WWW-Authenticate": "Bearer"}), 401, "invalid"),
        (HTTPException(403, "Forbidden"), 403, "Forbidden"),
    ],
)
def test_http_error_compatibility(error: Exception, status: int, detail: Any) -> None:
    response = exception_handler(error, {})
    assert response is not None
    assert response.status_code == status
    assert response.data == {"detail": detail}
    if status == 401:
        assert response["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("unique", [True, False])
def test_sqlalchemy_integrity_mapping(unique: bool) -> None:
    import sqlite3

    original = sqlite3.IntegrityError("constraint failed")
    original.sqlite_errorcode = sqlite3.SQLITE_CONSTRAINT_UNIQUE if unique else sqlite3.SQLITE_CONSTRAINT_NOTNULL
    error = IntegrityError("INSERT", {}, original)
    response = exception_handler(error, {})
    assert response.status_code == (409 if unique else 400)
    assert response.data == {
        "detail": ErrorResponse.respond(
            "This item already exists." if unique else "An unexpected error occurred.", exception=str(error)
        )
    }


def test_no_result_mapping() -> None:
    error = NoResultFound("missing")
    response = exception_handler(error, {})
    assert response.status_code == 404
    assert response.data == {"detail": ErrorResponse.respond("An unexpected error occurred.", exception=str(error))}


def test_drf_validation_mapping() -> None:
    response = exception_handler(DRFValidationError({"count": ["Invalid value"]}), {})
    assert response.status_code == 400
    assert response.data == {"detail": {"count": ["Invalid value"]}}


@pytest.mark.parametrize("production", [True, False])
def test_explicit_input_validation(production: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    class InputProbe(BaseModel):
        count: int

    assert validate_input(InputProbe, {"count": 3}).count == 3
    settings = get_app_settings()
    monkeypatch.setattr(settings, "PRODUCTION", production)
    monkeypatch.setattr(settings, "TESTING", False)
    with pytest.raises(RequestValidationError) as raised:
        validate_input(InputProbe, {"count": "invalid"})
    response = exception_handler(raised.value, {})
    assert response.status_code == 422
    if production:
        assert response.data["detail"][0]["loc"] == ["body", "count"]
        assert response.data["detail"][0]["type"] == "int_parsing"
    else:
        reference_request = StarletteRequest(
            {"type": "http", "method": "POST", "path": "/_test/input/", "headers": [], "query_string": b""}
        )
        reference = asyncio.run(fastapi_app.exception_handlers[RequestValidationError](reference_request, raised.value))
        assert response.data == json.loads(reference.body)
    with pytest.raises(ValidationError) as internal:
        InputProbe.model_validate({"count": "invalid"})
    assert exception_handler(internal.value, {}) is None
    assert exception_handler(RuntimeError("unexpected"), {}) is None
