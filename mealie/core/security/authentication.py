"""Framework-independent verification shared by FastAPI and DRF."""

from collections.abc import Callable
from datetime import timedelta

import jwt
from jwt.exceptions import PyJWTError
from sqlalchemy.orm import Session

from mealie.core.api_error import APIError
from mealie.core.config import get_app_settings
from mealie.core.exceptions import UserLockedOut
from mealie.core.root_logger import get_logger
from mealie.core.security.security import get_auth_provider
from mealie.core.security.tokens import ALGORITHM, create_access_token
from mealie.repos.all_repositories import AllRepositories, get_repositories
from mealie.schema.user import PrivateUser, TokenData
from mealie.schema.user.auth import CredentialsRequest


class AuthenticationError(APIError):
    pass


def credentials_error() -> AuthenticationError:
    return AuthenticationError(401, "Could not validate credentials", {"WWW-Authenticate": "Bearer"})


def extract_token(authorization: str | None, cookie: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() == "bearer":
        return token
    return cookie or ""


class TokenVerifier:
    def __init__(self, session: Session, repository_factory: Callable[..., AllRepositories] = get_repositories) -> None:
        self.session = session
        self.repository_factory = repository_factory

    def resolve(self, token: str) -> PrivateUser:
        settings = get_app_settings()
        try:
            payload = jwt.decode(token, settings.SECRET, algorithms=[ALGORITHM])
            user_id = payload.get("sub")
            if payload.get("long_token") is not None:
                return self.validate_api_token(token, payload.get("id"))
            if user_id is None:
                raise credentials_error()
            token_data = TokenData(user_id=user_id)
        except PyJWTError as exc:
            raise credentials_error() from exc

        repos = self.repository_factory(self.session, group_id=None, household_id=None)
        user = repos.users.get_one(token_data.user_id, "id", any_case=False)
        # Release the read transaction before subsequent request work.
        self.session.commit()
        if user is None:
            raise credentials_error()
        if user.tokens_valid_after is not None:
            issued_at = payload.get("iat")
            if issued_at is None or issued_at < user.tokens_valid_after.timestamp():
                raise credentials_error()
        return user

    def validate_api_token(self, token: str, user_id: str | None) -> PrivateUser:
        repos = self.repository_factory(self.session, group_id=None, household_id=None)
        tokens = repos.api_tokens.multi_query({"token": token, "user_id": user_id})
        try:
            user = tokens[0].user
            self.session.commit()
            return user
        except IndexError as exc:
            self.session.rollback()
            raise AuthenticationError(401, "Unauthorized") from exc


class SessionAuthenticationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def login(self, credentials: CredentialsRequest, ip: str) -> tuple[str, timedelta]:
        logger = get_logger("auth")
        try:
            auth = get_auth_provider(self.session, credentials).authenticate()
        except UserLockedOut as exc:
            logger.error(f"User is locked out from {ip}")
            raise AuthenticationError(423, "User is locked out") from exc
        if not auth:
            logger.error(f"Incorrect username or password from {ip}")
            raise AuthenticationError(401, "Unauthorized")
        return auth

    @staticmethod
    def refresh(user: PrivateUser, token: str) -> tuple[str, timedelta, bool]:
        try:
            payload = jwt.decode(token, get_app_settings().SECRET, algorithms=[ALGORITHM])
        except PyJWTError as exc:
            raise AuthenticationError(401, "Unauthorized") from exc
        if payload.get("long_token"):
            raise AuthenticationError(400, "API tokens cannot be exchanged for a session token")
        remember_me = bool(payload.get("rme", False))
        access_token, duration = create_access_token({"sub": str(user.id), "rme": remember_me})
        return access_token, duration, remember_me
