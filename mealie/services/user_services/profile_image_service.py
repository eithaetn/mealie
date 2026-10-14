import shutil
from typing import BinaryIO
from uuid import uuid4

from pydantic import UUID4

from mealie.core.api_error import APIError
from mealie.core.dependencies import get_temporary_path
from mealie.pkgs import cache, img
from mealie.repos.all_repositories import AllRepositories
from mealie.schema.user import PrivateUser
from mealie.services._base_service import BaseService
from mealie.services.user_services.permissions import assert_user_change_allowed


class ProfileImageService(BaseService):
    def __init__(self, repos: AllRepositories, user: PrivateUser) -> None:
        super().__init__()
        self.repos = repos
        self.user = user

    def update(self, user_id: UUID4, image_file: BinaryIO) -> None:
        with get_temporary_path() as temp_path:
            assert_user_change_allowed(user_id, self.user, self.user)
            temp_image = temp_path / str(uuid4())
            with temp_image.open("wb") as buffer:
                shutil.copyfileobj(image_file, buffer)
            image = img.PillowMinifier.to_webp(temp_image)
            destination = PrivateUser.get_directory(user_id) / "profile.webp"
            shutil.copyfile(image, destination)
        self.repos.users.patch(user_id, {"cache_key": cache.new_key()})
        if not destination.is_file():
            raise APIError(500, "Internal Server Error")
