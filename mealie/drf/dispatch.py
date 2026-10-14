from django.urls import Resolver404, resolve
from starlette.background import BackgroundTasks
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class DjangoAPIMiddleware:
    """Dispatch converted endpoints to Django, retaining the legacy API elsewhere.

    Kept inside Mealie's existing HTTP middleware so locale, CORS, compression,
    and session cookies continue to apply to both frameworks.
    """

    def __init__(self, app: ASGIApp) -> None:
        from mealie.drf.asgi import application

        self.app = app
        self.django = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        root_path = scope.get("root_path", "")
        if root_path and path.startswith(root_path + "/"):
            path = path[len(root_path) :]
        if scope["type"] == "http":
            try:
                match = resolve(path, urlconf="mealie.drf.urls")
            except Resolver404:
                pass
            else:
                # Migrate path/method pairs. Other methods can match an overlapping
                # legacy route (e.g. PUT /users/self matches /users/{item_id}).
                # Let that router retain its validation, authentication and Allow header.
                if scope["method"].lower() not in match.func.view_class.http_method_names:
                    await self.app(scope, receive, send)
                    return
                background = BackgroundTasks()
                scope["mealie.background_tasks"] = background
                status_code = 500
                complete = False

                async def track_response(message: Message) -> None:
                    nonlocal status_code, complete
                    if message["type"] == "http.response.start":
                        status_code = message["status"]
                    await send(message)
                    if message["type"] == "http.response.body" and not message.get("more_body", False):
                        complete = True

                await self.django(scope, receive, track_response)
                if complete and status_code < 400:
                    await background()
                return
        await self.app(scope, receive, send)
