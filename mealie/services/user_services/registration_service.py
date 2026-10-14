from logging import Logger
from uuid import uuid4

from fastapi import HTTPException, status
from pydantic import UUID4

from mealie.core.api_error import APIError
from mealie.core.config import get_app_settings
from mealie.core.security import hash_password
from mealie.lang.providers import Translator
from mealie.repos.all_repositories import get_repositories
from mealie.repos.repository_factory import AllRepositories
from mealie.schema.group.group_preferences import CreateGroupPreferences
from mealie.schema.household.household import HouseholdCreate, HouseholdInDB
from mealie.schema.household.household_preferences import CreateHouseholdPreferences
from mealie.schema.response import ErrorResponse
from mealie.schema.user.registration import CreateUserRegistration
from mealie.schema.user.user import GroupBase, GroupInDB, PrivateUser, UserIn, UserOut
from mealie.services.event_bus_service.event_bus_service import EventBusService
from mealie.services.event_bus_service.event_types import EventTypes, EventUserSignupData
from mealie.services.group_services.group_service import GroupService
from mealie.services.household_services.household_service import HouseholdService
from mealie.services.seeder.seeder_service import SeederService


class RegistrationService:
    logger: Logger
    repos: AllRepositories

    def __init__(self, logger: Logger, db: AllRepositories, translator: Translator):
        self.logger = logger
        self.repos = db
        self.t = translator.t

    def register_public_user(self, registration: CreateUserRegistration, event_bus: EventBusService) -> UserOut:
        if (not get_app_settings().ALLOW_SIGNUP and registration.group_token is None) or registration.group_token == "":
            raise APIError(403, ErrorResponse.respond("User Registration is Disabled"))
        user = self.register_user(registration)
        event_bus.dispatch(
            integration_id="registration",
            group_id=user.group_id,
            household_id=user.household_id,
            event_type=EventTypes.user_signup,
            document_data=EventUserSignupData(username=user.username, email=user.email),
        )
        return UserOut.model_validate(user.model_dump())

    def _create_new_user(self, group: GroupInDB, household: HouseholdInDB, new_group: bool) -> PrivateUser:
        new_user = UserIn(
            email=self.registration.email,
            username=self.registration.username,
            password=hash_password(self.registration.password),
            full_name=self.registration.full_name,
            advanced=self.registration.advanced,
            group=group,
            household=household,
            can_invite=new_group,
            can_manage=new_group,
            can_manage_household=new_group,
            can_organize=new_group,
        )

        # TODO: problem with repository type, not type here
        return self.repos.users.create(new_user)  # type: ignore

    def _register_new_group(self) -> GroupInDB:
        group_data = GroupBase(name=self.registration.group)

        group_preferences = CreateGroupPreferences(
            group_id=uuid4(),
            private_group=self.registration.private,
        )

        return GroupService.create_group(self.repos, group_data, group_preferences)

    def _fetch_or_register_new_household(self, group_id: UUID4) -> HouseholdInDB:
        settings = get_app_settings()
        new_household_name = self.registration.household or settings.DEFAULT_HOUSEHOLD

        group_repos = get_repositories(self.repos.session, group_id=group_id)
        household_fetch = group_repos.households.get_by_name(new_household_name)
        if household_fetch:
            return household_fetch

        household_data = HouseholdCreate(name=new_household_name)
        household_preferences = CreateHouseholdPreferences(
            private_household=self.registration.private,
            first_day_of_week=0,
            recipe_public=not self.registration.private,
            recipe_show_nutrition=self.registration.advanced,
            recipe_show_assets=self.registration.advanced,
            recipe_landscape_view=False,
            recipe_disable_comments=self.registration.advanced,
        )
        return HouseholdService.create_household(group_repos, household_data, household_preferences)

    def register_user(self, registration: CreateUserRegistration) -> PrivateUser:
        self.registration = registration

        if self.repos.users.get_by_username(registration.username):
            raise HTTPException(status.HTTP_409_CONFLICT, {"message": self.t("exceptions.username-conflict-error")})
        elif self.repos.users.get_one(registration.email, "email"):
            raise HTTPException(status.HTTP_409_CONFLICT, {"message": self.t("exceptions.email-conflict-error")})

        token_entry = None
        new_group = False

        if registration.group_token:
            token_entry = self.repos.group_invite_tokens.get_one(registration.group_token)
            if not token_entry:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, {"message": "Invalid group token"})

            maybe_none_group = self.repos.groups.get_one(token_entry.group_id)
            if maybe_none_group is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, {"message": "Invalid group token"})
            group = maybe_none_group

            maybe_none_household = self.repos.households.get_one(token_entry.household_id)
            if maybe_none_household is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, {"message": "Invalid group token"})
            household = maybe_none_household
        elif registration.group:
            new_group = True
            group = self._register_new_group()
            household = self._fetch_or_register_new_household(group.id)
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, {"message": "Missing group"})

        self.logger.info(f"Registering user {registration.username}")
        user = self._create_new_user(group, household, new_group)

        if new_group and registration.seed_data:
            group_repos = get_repositories(self.repos.session, group_id=group.id)
            seeder_service = SeederService(group_repos)
            seeder_service.seed_foods(registration.locale)
            seeder_service.seed_units(registration.locale)

        if token_entry and user:
            token_entry.uses_left = token_entry.uses_left - 1

            if token_entry.uses_left == 0:
                self.repos.group_invite_tokens.delete(token_entry.token)

            else:
                self.repos.group_invite_tokens.update(token_entry.token, token_entry)

        return user
