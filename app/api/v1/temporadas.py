from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.temporada import TemporadaCreate, TemporadaUpdate, TemporadaResponse
from app.servicios.temporada_service import TemporadaService
from app.api.dependencias import get_current_user, require_admin, require_roles

router = APIRouter(prefix="/seasons", tags=["Seasons & Collections"])


@router.get(
    "",
    response_model=List[TemporadaResponse],
    status_code=status.HTTP_200_OK,
    summary="List all seasons and collections",
)
def list_seasons(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by season name"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    seasons = TemporadaService.list_seasons(db, is_active=is_active, search=search)
    return [TemporadaService.format_response(s) for s in seasons]


@router.post(
    "",
    response_model=TemporadaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create season (Admin and Store Manager)",
)
def create_season(
    request: TemporadaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    season = TemporadaService.create_season(db, request)
    return TemporadaService.format_response(season)


@router.get(
    "/{season_id}",
    response_model=TemporadaResponse,
    status_code=status.HTTP_200_OK,
    summary="Get season by ID",
)
def get_season(
    season_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    season = TemporadaService.get_season_by_id(db, season_id)
    return TemporadaService.format_response(season)


@router.put(
    "/{season_id}",
    response_model=TemporadaResponse,
    status_code=status.HTTP_200_OK,
    summary="Update season (Admin and Store Manager)",
)
def update_season(
    season_id: str,
    request: TemporadaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    season = TemporadaService.update_season(db, season_id, request)
    return TemporadaService.format_response(season)


@router.patch(
    "/{season_id}/toggle-status",
    response_model=TemporadaResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle season active status (Admin and Store Manager)",
)
def toggle_status(
    season_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    season = TemporadaService.toggle_status(db, season_id)
    return TemporadaService.format_response(season)
