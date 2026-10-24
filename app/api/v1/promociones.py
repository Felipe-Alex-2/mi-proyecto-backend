from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.promocion import PromocionCreate, PromocionUpdate, PromocionResponse
from app.servicios.promocion_service import PromocionService
from app.api.dependencias import get_current_user, require_admin, require_roles

router = APIRouter(prefix="/promotions", tags=["Promotions & Discounts"])


@router.get(
    "",
    response_model=List[PromocionResponse],
    status_code=status.HTTP_200_OK,
    summary="List all promotions and discounts",
)
def list_promotions(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by promotion name"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    promotions = PromocionService.list_promotions(db, is_active=is_active, search=search)
    return [PromocionService.format_response(p) for p in promotions]


@router.post(
    "",
    response_model=PromocionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create promotion (Admin and Store Manager)",
)
def create_promotion(
    request: PromocionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    promotion = PromocionService.create_promotion(db, request)
    return PromocionService.format_response(promotion)


@router.get(
    "/{promotion_id}",
    response_model=PromocionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get promotion by ID",
)
def get_promotion(
    promotion_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    promotion = PromocionService.get_promotion_by_id(db, promotion_id)
    return PromocionService.format_response(promotion)


@router.put(
    "/{promotion_id}",
    response_model=PromocionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update promotion (Admin and Store Manager)",
)
def update_promotion(
    promotion_id: str,
    request: PromocionUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    promotion = PromocionService.update_promotion(db, promotion_id, request)
    return PromocionService.format_response(promotion)


@router.patch(
    "/{promotion_id}/toggle-status",
    response_model=PromocionResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle promotion active status (Admin and Store Manager)",
)
def toggle_status(
    promotion_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    promotion = PromocionService.toggle_status(db, promotion_id)
    return PromocionService.format_response(promotion)
