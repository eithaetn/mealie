from starlette.types import ASGIApp, Receive, Scope, Send


class ASGIDispatcher:
    """Route selected HTTP paths, leaving FastAPI in charge of lifespan and websockets."""

    def __init__(
        self,
        fastapi_app: ASGIApp,
        django_app: ASGIApp,
        *,
        ported_prefixes: tuple[str, ...] = (),
        infrastructure_paths: tuple[str, ...] = (),
    ) -> None:
        self.fastapi_app = fastapi_app
        self.django_app = django_app
        self.ported_prefixes = ported_prefixes
        self.infrastructure_paths = infrastructure_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        target = self.fastapi_app
        if scope["type"] == "http":
            path = scope["path"]
            root_path = scope.get("root_path", "").rstrip("/")
            if root_path and (path == root_path or path.startswith(root_path + "/")):
                path = path[len(root_path) :]
            if path in self.infrastructure_paths or any(
                path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
                for prefix in self.ported_prefixes
            ):
                target = self.django_app
        await target(scope, receive, send)
