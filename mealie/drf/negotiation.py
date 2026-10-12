from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request


class JSONContentNegotiation(DefaultContentNegotiation):
    def select_renderer(
        self, request: Request, renderers: list[BaseRenderer], format_suffix: str | None = None
    ) -> tuple[BaseRenderer, str]:
        # Existing API returns JSON regardless of the client's Accept header.
        return renderers[0], renderers[0].media_type
