from starlette.datastructures import MutableHeaders
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mealie.core.config import get_app_settings


class TagHTTPMiddleware:
    """Retain FastAPI's compression and signed-session headers for Tags only."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.tags_app = ServerErrorMiddleware(
            SessionMiddleware(
                GZipMiddleware(self.buffered_app, minimum_size=1000), secret_key=get_app_settings().SESSION_SECRET
            )
        )

    async def buffered_app(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Tags are non-streaming JSON endpoints. Django splits large responses
        # into ASGI chunks; coalesce them so gzip and Content-Length match FastAPI.
        start: Message | None = None
        body = bytearray()

        async def buffered_send(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    assert start is not None
                    MutableHeaders(scope=start)["Content-Length"] = str(len(body))
                    await send(start)
                    await send({"type": "http.response.body", "body": bytes(body)})
            else:
                await send(message)

        await self.app(scope, receive, buffered_send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        root_path = scope.get("root_path", "").rstrip("/")
        if root_path and (path == root_path or path.startswith(root_path + "/")):
            path = path[len(root_path) :]
        prefix = "/api/organizers/tags"
        target = (
            self.tags_app if scope["type"] == "http" and (path == prefix or path.startswith(prefix + "/")) else self.app
        )
        await target(scope, receive, send)


class TagErrorHeaders:
    """Match FastAPI's outer server-error layer, including development CORS."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        root_path = scope.get("root_path", "").rstrip("/")
        if root_path and (path == root_path or path.startswith(root_path + "/")):
            path = path[len(root_path) :]
        if scope["type"] != "http" or not (path == "/api/organizers/tags" or path.startswith("/api/organizers/tags/")):
            await self.app(scope, receive, send)
            return
        plain_error = False

        async def error_send(message: Message) -> None:
            nonlocal plain_error
            if message["type"] == "http.response.start":
                message["headers"] = [(name.lower(), value) for name, value in message.get("headers", [])]
                headers = MutableHeaders(scope=message)
                plain_error = message["status"] == 500 and headers.get("content-type", "").startswith("text/")
                if plain_error:
                    for key in list(headers):
                        if key.startswith("access-control-") or key in {"content-encoding", "vary"}:
                            del headers[key]
                    headers["Content-Type"] = "text/plain; charset=utf-8"
                    headers["Content-Length"] = str(len(b"Internal Server Error"))
            elif message["type"] == "http.response.body" and plain_error:
                if not message.get("more_body", False):
                    await send({"type": "http.response.body", "body": b"Internal Server Error"})
                return
            await send(message)

        await self.app(scope, receive, error_send)
