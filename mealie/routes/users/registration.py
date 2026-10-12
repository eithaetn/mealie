from fastapi import APIRouter, Depends, HTTPException, status

from mealie.core.api_error import APIError
from mealie.repos.all_repositories import get_repositories
from mealie.routes._base import BasePublicController, controller
from mealie.schema.user.registration import CreateUserRegistration
from mealie.schema.user.user import UserOut
from mealie.services.event_bus_service.event_bus_service import EventBusService
from mealie.services.user_services.registration_service import RegistrationService

router = APIRouter(prefix="/register")


@controller(router)
class RegistrationController(BasePublicController):
    event_bus: EventBusService = Depends(EventBusService.as_dependency)

    @router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
    def register_new_user(self, data: CreateUserRegistration) -> UserOut:
        service = RegistrationService(
            self.logger, get_repositories(self.session, group_id=None, household_id=None), self.translator
        )
        try:
            return service.register_public_user(data, self.event_bus)
        except APIError as exc:
            raise HTTPException(exc.status_code, exc.detail, headers=exc.headers) from exc
