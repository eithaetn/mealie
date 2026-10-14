from django.http import HttpRequest, HttpResponse


def server_error(request: HttpRequest) -> HttpResponse:
    """Keep the existing API's opaque response for unhandled server errors."""
    return HttpResponse("Internal Server Error", status=500, content_type="text/plain; charset=utf-8")
