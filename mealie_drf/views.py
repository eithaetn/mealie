from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


@extend_schema(exclude=True)
@api_view(["GET"])
def health(request: Request) -> Response:
    """Verify the DRF shell without accessing authentication or persistence."""
    return Response({"status": "ok"})
