from sqlalchemy.orm import Session

from mealie.core.settings.static import APP_VERSION
from mealie.repos.all_repositories import get_repositories
from mealie.schema.admin.about import AppInfo, AppStartupInfo, AppTheme
from mealie.services._base_service import BaseService


class AppInfoService(BaseService):
    def get_info(self, session: Session) -> AppInfo:
        settings = self.settings
        public_repos = get_repositories(session, group_id=None, household_id=None)
        default_group_slug: str | None = None
        default_household_slug: str | None = None
        default_group = public_repos.groups.get_by_name(settings.DEFAULT_GROUP)
        if default_group and default_group.preferences and not default_group.preferences.private_group:
            default_group_slug = default_group.slug

        if default_group and default_group_slug:
            group_repos = get_repositories(session, group_id=default_group.id, household_id=None)
            default_household = group_repos.households.get_by_name(settings.DEFAULT_HOUSEHOLD)
            if (
                default_household
                and default_household.preferences
                and not default_household.preferences.private_household
            ):
                default_household_slug = default_household.slug

        return AppInfo(
            version=APP_VERSION,
            demo_status=settings.IS_DEMO,
            production=settings.PRODUCTION,
            allow_signup=settings.ALLOW_SIGNUP,
            default_group_slug=default_group_slug,
            default_household_slug=default_household_slug,
            enable_oidc=settings.OIDC_READY,
            oidc_redirect=settings.OIDC_AUTO_REDIRECT,
            oidc_provider_name=settings.OIDC_PROVIDER_NAME,
            allow_password_login=settings.ALLOW_PASSWORD_LOGIN,
            token_time=settings.TOKEN_TIME,
            allowed_iframe_hosts=settings.allowed_iframe_hosts,
        )

    def get_startup_info(self, session: Session) -> AppStartupInfo:
        repos = get_repositories(session, group_id=None, household_id=None)
        return AppStartupInfo(
            is_first_login=repos.users.count_all("email", self.settings._DEFAULT_EMAIL) > 0,
            is_demo=self.settings.IS_DEMO,
        )

    def get_theme(self) -> AppTheme:
        return AppTheme(**self.settings.theme.model_dump())
