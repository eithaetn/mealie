from datetime import timedelta

from starlette.requests import Request
from starlette.responses import Response

SESSION_COOKIE_NAME = "mealie.access_token"


def request_is_https(request: Request) -> bool:
    """Whether the browser reached Mealie over HTTPS.

    `request.url.scheme` only reflects the browser's own connection when uvicorn's proxy-header
    handling trusted the proxy, which it stops doing as soon as an admin narrows `HOST_IP` from its
    default. Falling back to the header keeps `Secure` — and with it the embedded `SameSite=None`
    path — working behind a proxy Mealie hasn't been told to trust.

    Reading it unverified is safe here in a way it wouldn't be for authorization: it only alters
    attributes on the sender's own cookie in the same response, so forging it achieves nothing beyond
    breaking your own session.
    """
    if request.url.scheme == "https":
        return True

    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    # a chain of proxies appends to this, and the client's own protocol is the first entry
    return forwarded_proto.split(",")[0].strip().lower() == "https"


def session_cookie_attrs(request: Request) -> dict:
    """Cookie attributes that have to match between setting and clearing the session cookie.

    Mealie is sometimes embedded in another site, which needs `SameSite=None` and a partitioned
    cookie. The server can't detect embedding, so the client flags it — and we only honour the flag
    over HTTPS, since browsers reject `SameSite=None` without `Secure`.
    """
    secure = request_is_https(request)
    embedded = secure and request.headers.get("x-mealie-embedded", "").lower() == "true"

    return {
        "path": "/",
        "secure": secure,
        "samesite": "none" if embedded else "lax",
        "partitioned": embedded,
    }


def set_session_cookie(response: Response, request: Request, token: str, expires_in: timedelta, remember_me: bool):
    """Sends the session cookie from the server instead of letting the client write it.

    Safari caps any cookie created through `document.cookie` at seven days, whatever max-age it asks
    for, which silently truncated every iOS session regardless of TOKEN_TIME. Cookies that arrive on
    a Set-Cookie header aren't subject to that cap.
    """
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        # Remember-me decides whether the cookie outlives the browser session. Omitting max-age makes
        # it a session cookie; the token is valid for TOKEN_TIME either way.
        max_age=int(expires_in.total_seconds()) if remember_me else None,
        # The SPA reads this to set its Authorization header, so it can't be HttpOnly yet.
        httponly=False,
        **session_cookie_attrs(request),
    )
