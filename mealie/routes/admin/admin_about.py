from fastapi import APIRouter

from mealie.routes._base import BaseAdminController, controller
from mealie.schema.admin.about import AdminAboutInfo, AppStatistics, CheckAppConfig
from mealie.services.admin_about_service import AdminAboutService

router = APIRouter(prefix="/about")


@controller(router)
class AdminAboutController(BaseAdminController):
    @router.get("", response_model=AdminAboutInfo)
    def get_app_info(self) -> AdminAboutInfo:
        return AdminAboutService(self.repos).get_info()

    @router.get("/statistics", response_model=AppStatistics)
    def get_app_statistics(self) -> AppStatistics:
        return AdminAboutService(self.repos).get_statistics()

    @router.get("/check", response_model=CheckAppConfig)
    def check_app_config(self) -> CheckAppConfig:
        return AdminAboutService(self.repos).check_config()
