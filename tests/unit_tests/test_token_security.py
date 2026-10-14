from datetime import timedelta
from pathlib import Path

import jwt
import pytest
from fastapi import HTTPException

from mealie.core import security
from mealie.core.config import get_app_dirs, get_app_settings
from mealie.core.dependencies import validate_file_token
from mealie.routes.utility_routes import download_file


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_app_settings().SECRET, algorithms=[security.ALGORITHM])


def test_create_access_token_defaults_to_token_time():
    settings = get_app_settings()
    token, duration = security.create_access_token({"sub": "abc"})

    assert duration == timedelta(hours=settings.TOKEN_TIME)

    payload = decode_token(token)
    assert payload["sub"] == "abc"
    # the returned duration is what clients schedule against, so it must match the token's own claims
    assert payload["exp"] - payload["iat"] == duration.total_seconds()


def test_create_access_token_honors_an_explicit_lifetime():
    token, duration = security.create_access_token({"sub": "abc"}, timedelta(minutes=5))

    assert duration == timedelta(minutes=5)

    payload = decode_token(token)
    assert payload["exp"] - payload["iat"] == 5 * 60


def test_every_token_is_stamped_with_issuer_and_issued_at():
    """One factory signs session, API and file tokens, so all three carry the same base claims."""
    session_token, _ = security.create_access_token({"sub": "abc"})
    file_token = security.create_file_token(Path(__file__))

    for token in (session_token, file_token):
        payload = decode_token(token)
        assert payload["iss"] == security.ISS
        assert payload["iat"]


def test_create_file_token():
    file_path = Path(__file__).parent
    file_token = security.create_file_token(file_path)

    assert file_path == validate_file_token(file_token)


def test_validate_file_token_rejects_a_token_without_a_file_claim():
    """Session and API tokens share the signing secret, so they decode here — the claim is the check.

    Previously these raised TypeError on `Path(None)`, surfacing as a 500 instead of the documented
    401.
    """
    session_token, _ = security.create_access_token({"sub": "abc"})

    with pytest.raises(HTTPException) as exc_info:
        validate_file_token(session_token)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_download_file_security_restrictions():
    dirs = get_app_dirs()

    # Test 1: File in DATA_DIR but outside allowed dirs should be blocked
    secret_file = dirs.DATA_DIR / ".secret"

    with pytest.raises(HTTPException) as exc_info:
        await download_file(secret_file)
    assert exc_info.value.status_code == 400

    # Test 2: File in BACKUP_DIR should be allowed (but only if it exists)
    backup_file = dirs.BACKUP_DIR / "test.zip"
    dirs.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_file.write_text("test backup content")

    try:
        response = await download_file(backup_file)
        assert response.media_type == "application/octet-stream"
        assert response.path == backup_file
    finally:
        backup_file.unlink(missing_ok=True)

    # Test 3: File in GROUPS_DIR should be allowed (but only if it exists)
    export_dir = dirs.GROUPS_DIR / "some-group-id" / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_file = export_dir / "test.zip"
    export_file.write_text("test export content")

    try:
        response = await download_file(export_file)
        assert response.media_type == "application/octet-stream"
        assert response.path == export_file
    finally:
        export_file.unlink(missing_ok=True)
        # Clean up the directory structure
        export_dir.rmdir()
        (dirs.GROUPS_DIR / "some-group-id").rmdir()
