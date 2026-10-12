from datetime import timedelta

from mealie.core.security.authentication import AuthenticationError
from mealie.core.security.tokens import create_access_token
from mealie.repos.all_repositories import AllRepositories
from mealie.schema.user import (
    CreateToken,
    DeleteTokenResponse,
    LongLiveTokenCreateResponse,
    LongLiveTokenIn,
    PrivateUser,
)
from mealie.services._base_service import BaseService


class ApiTokenService(BaseService):
    def __init__(self, repos: AllRepositories, user: PrivateUser) -> None:
        super().__init__()
        self.repos = repos
        self.user = user

    def create(self, data: LongLiveTokenIn) -> LongLiveTokenCreateResponse:
        token, _ = create_access_token(
            {
                "long_token": True,
                "id": str(self.user.id),
                "name": data.name,
                "integration_id": data.integration_id,
            },
            timedelta(1825),
        )
        created = self.repos.api_tokens.create(CreateToken(name=data.name, token=token, user_id=self.user.id))
        return LongLiveTokenCreateResponse.model_validate(created.model_dump())

    def delete(self, token_id: int) -> DeleteTokenResponse:
        token = self.repos.api_tokens.get_one(token_id)
        if not token:
            raise AuthenticationError(404, f"Could not locate token with id '{token_id}' in database")
        if token.user_id != self.user.id:
            raise AuthenticationError(403, "Forbidden")
        deleted = self.repos.api_tokens.delete(token_id)
        return DeleteTokenResponse(token_delete=deleted.name)
