from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.season import SeasonCreate, SeasonUpdate, SeasonResponse
from app.services.season_service import SeasonService
from app.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/seasons", tags=["Seasons & Collections"])


@router.get(
    "",
    response_model=List[SeasonResponse],
    status_code=status.HTTP_200_OK,
    summary="List all seasons and collections",
)
def list_seasons(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by season name"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    seasons = SeasonService.list_seasons(db, is_active=is_active, search=search)
    return [SeasonService.format_response(s) for s in seasons]


@router.post(
    "",
    response_model=SeasonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create season (Admin only)",
)
def create_season(
    request: SeasonCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    season = SeasonService.create_season(db, request)
    return SeasonService.format_response(season)


@router.get(
    "/{season_id}",
    response_model=SeasonResponse,
    status_code=status.HTTP_200_OK,
    summary="Get season by ID",
)
def get_season(
    season_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    season = SeasonService.get_season_by_id(db, season_id)
    return SeasonService.format_response(season)


@router.put(
    "/{season_id}",
    response_model=SeasonResponse,
    status_code=status.HTTP_200_OK,
    summary="Update season (Admin only)",
)
def update_season(
    season_id: str,
    request: SeasonUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    season = SeasonService.update_season(db, season_id, request)
    return SeasonService.format_response(season)


@router.patch(
    "/{season_id}/toggle-status",
    response_model=SeasonResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle season active status (Admin only)",
)
def toggle_status(
    season_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    season = SeasonService.toggle_status(db, season_id)
    return SeasonService.format_response(season)
