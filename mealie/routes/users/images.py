from fastapi import File, HTTPException, UploadFile
from pydantic import UUID4

from mealie.core.api_error import APIError
from mealie.routes._base import BaseUserController, controller
from mealie.routes._base.routers import UserAPIRouter
from mealie.services.user_services.profile_image_service import ProfileImageService

router = UserAPIRouter(prefix="", tags=["Users: Images"])


@controller(router)
class UserImageController(BaseUserController):
    @router.post("/{id}/image", response_model=None)
    def update_user_image(self, id: UUID4, profile: UploadFile = File(...)) -> None:
        try:
            ProfileImageService(self.repos, self.user).update(id, profile.file)
        except APIError as exc:
            raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc
