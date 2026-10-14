from mealie.core.release_checker import get_latest_version
from mealie.core.settings.static import APP_VERSION
from mealie.repos.all_repositories import AllRepositories
from mealie.schema.admin.about import AdminAboutInfo, AppStatistics, CheckAppConfig
from mealie.services._base_service import BaseService


class AdminAboutService(BaseService):
    def __init__(self, repos: AllRepositories) -> None:
        super().__init__()
        self.repos = repos

    def get_info(self) -> AdminAboutInfo:
        from recipe_scrapers import __version__ as recipe_scraper_version

        settings = self.settings
        return AdminAboutInfo(
            production=settings.PRODUCTION,
            version=APP_VERSION,
            versionLatest=get_latest_version(),
            demo_status=settings.IS_DEMO,
            api_port=settings.API_PORT,
            api_docs=settings.API_DOCS,
            db_type=settings.DB_ENGINE,
            db_url=settings.DB_URL_PUBLIC,
            default_group=settings.DEFAULT_GROUP,
            default_household=settings.DEFAULT_HOUSEHOLD,
            allow_signup=settings.ALLOW_SIGNUP,
            allow_password_login=settings.ALLOW_PASSWORD_LOGIN,
            token_time=settings.TOKEN_TIME,
            build_id=settings.GIT_COMMIT_HASH,
            recipe_scraper_version=recipe_scraper_version.__version__,
            enable_oidc=settings.OIDC_AUTH_ENABLED,
            oidc_redirect=settings.OIDC_AUTO_REDIRECT,
            oidc_provider_name=settings.OIDC_PROVIDER_NAME,
        )

    def get_statistics(self) -> AppStatistics:
        return AppStatistics(
            total_recipes=self.repos.recipes.count_all(),
            uncategorized_recipes=self.repos.recipes.count_uncategorized(),
            untagged_recipes=self.repos.recipes.count_untagged(),
            total_users=self.repos.users.count_all(),
            total_households=self.repos.households.count_all(),
            total_groups=self.repos.groups.count_all(),
        )

    def check_config(self) -> CheckAppConfig:
        settings = self.settings
        return CheckAppConfig(
            email_ready=settings.SMTP_ENABLE,
            ldap_ready=settings.LDAP_ENABLED,
            ldap_disabled=not settings.LDAP_AUTH_ENABLED,
            base_url_set=settings.BASE_URL != "http://localhost:8080",
            is_up_to_date=APP_VERSION in {"develop", "nightly"} or get_latest_version() == APP_VERSION,
            oidc_ready=settings.OIDC_READY,
            oidc_disabled=not settings.OIDC_AUTH_ENABLED,
        )
