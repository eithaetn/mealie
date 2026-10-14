from django.http import HttpRequest
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.types import Message


async def parse_form(request: HttpRequest) -> FormData:
    """Retain the API's multipart limits and upload semantics during migration.

    Django has already spooled the ASGI request body. Feed it to the existing
    multipart parser in chunks instead of materializing uploaded files in memory.
    """

    async def receive() -> Message:
        chunk = request.read(64 * 1024)
        return {"type": "http.request", "body": chunk, "more_body": bool(chunk)}

    return await Request(request.scope, receive).form()
