from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from mealie.db.db_setup import generate_session
from mealie.schema.admin.about import AppInfo, AppStartupInfo, AppTheme
from mealie.services.app_info_service import AppInfoService

router = APIRouter(prefix="/about")

# Retain route declarations for the existing OpenAPI/type generation pipeline.
# Live requests to these paths are dispatched to native DRF views.


@router.get("", response_model=AppInfo)
def get_app_info(session: Session = Depends(generate_session)) -> AppInfo:
    return AppInfoService().get_info(session)


@router.get("/startup-info", response_model=AppStartupInfo)
def get_startup_info(session: Session = Depends(generate_session)) -> AppStartupInfo:
    return AppInfoService().get_startup_info(session)


@router.get("/theme", response_model=AppTheme)
def get_app_theme(resp: Response) -> AppTheme:
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return AppInfoService().get_theme()
