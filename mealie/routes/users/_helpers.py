from fastapi import HTTPException
from pydantic import UUID4

from mealie.core.api_error import APIError
from mealie.schema.user.user import PrivateUser, UserBase
from mealie.services.user_services.permissions import assert_user_change_allowed as check_user_change


def assert_user_change_allowed(user_id: UUID4, current_user: PrivateUser, new_data: UserBase) -> None:
    try:
        check_user_change(user_id, current_user, new_data)
    except APIError as exc:
        raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc
