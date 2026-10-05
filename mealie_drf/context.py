from dataclasses import dataclass
from functools import cached_property
from uuid import UUID

from rest_framework.request import Request
from sqlalchemy.orm import Session

from mealie.repos.all_repositories import AllRepositories, get_repositories
from mealie.schema.user import PrivateUser


@dataclass
class MealieRequestContext:
    user: PrivateUser
    session: Session

    @property
    def group_id(self) -> UUID:
        return self.user.group_id

    @property
    def household_id(self) -> UUID:
        return self.user.household_id

    @cached_property
    def repos(self) -> AllRepositories:
        return get_repositories(self.session, group_id=self.group_id, household_id=self.household_id)


def get_request_context(request: Request) -> MealieRequestContext:
    context = getattr(request, "mealie_context", None)
    if not isinstance(context, MealieRequestContext):
        raise RuntimeError("Mealie request context requires MealieAPIView authentication")
    return context


def get_request_session(request: Request) -> Session:
    session = getattr(request, "mealie_session", None)
    if not isinstance(session, Session):
        raise RuntimeError("Mealie request session requires MealieAPIView")
    return session
