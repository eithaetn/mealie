from mealie.core.api_error import APIError
from mealie.core.security import url_safe_token
from mealie.repos.all_repositories import AllRepositories
from mealie.schema.household.invite_token import (
    CreateInviteToken,
    EmailInitationResponse,
    EmailInvitation,
    ReadInviteToken,
    SaveInviteToken,
)
from mealie.schema.response.pagination import PaginationQuery
from mealie.schema.user.user import PrivateUser
from mealie.services._base_service import BaseService
from mealie.services.email.email_service import EmailService


class InvitationService(BaseService):
    def __init__(self, repos: AllRepositories, user: PrivateUser) -> None:
        super().__init__()
        self.repos = repos
        self.user = user

    def list_tokens(self) -> list[ReadInviteToken]:
        if not self.user.admin:
            raise APIError(403, "Only admins can list invite tokens")
        return self.repos.group_invite_tokens.page_all(PaginationQuery(page=1, per_page=-1)).items

    def create(self, data: CreateInviteToken) -> ReadInviteToken:
        if not self.settings.ALLOW_PASSWORD_LOGIN:
            raise APIError(403, "Invitation tokens are disabled when password login is not allowed")
        if not self.user.can_invite:
            raise APIError(403, "User is not allowed to create invite tokens")
        group_id = data.group_id or self.user.group_id
        household_id = data.household_id or self.user.household_id
        if not self.user.admin and (group_id != self.user.group_id or household_id != self.user.household_id):
            raise APIError(403, "Only admins can create invite tokens for other groups or households")
        return self.repos.group_invite_tokens.create(
            SaveInviteToken(uses_left=data.uses, group_id=group_id, household_id=household_id, token=url_safe_token())
        )

    def email(self, data: EmailInvitation, locale: str | None) -> EmailInitationResponse:
        if not self.settings.ALLOW_PASSWORD_LOGIN:
            raise APIError(403, "Invitation email are disabled when password login is not allowed")
        if not self.user.can_invite:
            raise APIError(403, "This user can't send email invitations")
        email_service = EmailService(locale=locale)
        url = f"{self.settings.BASE_URL}/register?token={data.token}"
        success = False
        error = None
        try:
            success = email_service.send_invitation(address=data.email, invitation_url=url)
        except Exception as exc:
            error = str(exc)
        return EmailInitationResponse(success=success, error=error)
