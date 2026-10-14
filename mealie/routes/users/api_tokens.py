from fastapi import HTTPException, status

from mealie.core.security.authentication import AuthenticationError
from mealie.routes._base import BaseUserController, controller
from mealie.routes._base.routers import UserAPIRouter
from mealie.schema.user import DeleteTokenResponse, LongLiveTokenCreateResponse, LongLiveTokenIn
from mealie.services.api_token_service import ApiTokenService

router = UserAPIRouter(prefix="/users", tags=["Users: Tokens"])


@controller(router)
class UserApiTokensController(BaseUserController):
    @router.post("/api-tokens", status_code=status.HTTP_201_CREATED, response_model=LongLiveTokenCreateResponse)
    def create_api_token(self, token_params: LongLiveTokenIn) -> LongLiveTokenCreateResponse:
        return ApiTokenService(self.repos, self.user).create(token_params)

    @router.delete("/api-tokens/{token_id}", response_model=DeleteTokenResponse)
    def delete_api_token(self, token_id: int) -> DeleteTokenResponse:
        try:
            return ApiTokenService(self.repos, self.user).delete(token_id)
        except AuthenticationError as exc:
            raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc
