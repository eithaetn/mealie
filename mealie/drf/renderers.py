from typing import Any

from rest_framework.renderers import JSONRenderer


class MealieJSONRenderer(JSONRenderer):
    def render(self, data: Any, accepted_media_type: str | None = None, renderer_context: dict | None = None) -> bytes:
        # FastAPI encodes a successful None result as JSON null; DRF otherwise
        # sends an empty body, which breaks clients that call response.json().
        response = (renderer_context or {}).get("response")
        if data is None and (response is None or response.status_code not in {204, 304}):
            return b"null"
        return super().render(data, accepted_media_type, renderer_context)
