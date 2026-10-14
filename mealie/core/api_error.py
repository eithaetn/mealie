from typing import Any


class APIError(Exception):
    """An application error that HTTP controllers can translate without framework coupling."""

    def __init__(self, status_code: int, detail: Any, headers: dict[str, str] | None = None) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}
