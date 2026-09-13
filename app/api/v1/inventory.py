from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_roles
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.inventory_movement import (
    InventoryMovementCreate,
    InventoryMovementResponse,
    BranchInventorySummary,
)
from app.services.inventory_movement_service import InventoryMovementService

router = APIRouter(prefix="/inventory", tags=["Inventory Movements (CU09)"])


@router.post(
    "/movements",
    response_model=InventoryMovementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un movimiento de inventario (Entrada, Salida, Ajuste, Devolución)",
)
def create_movement(
    payload: InventoryMovementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.STORE_MANAGER)),
):
    return InventoryMovementService.create_movement(db=db, user=current_user, data=payload)


@router.get(
    "/movements",
    response_model=List[InventoryMovementResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar historial de movimientos de inventario con filtros",
)
def list_movements(
    branch_id: Optional[str] = Query(None, description="Filtrar por sucursal"),
    type: Optional[str] = Query(None, description="Filtrar por tipo (ENTRY, EXIT, ADJUSTMENT, RETURN)"),
    variant_id: Optional[str] = Query(None, description="Filtrar por ID de variante"),
    product_id: Optional[str] = Query(None, description="Filtrar por ID de producto"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.STORE_MANAGER)),
):
    return InventoryMovementService.list_movements(
        db=db,
        user=current_user,
        branch_id=branch_id,
        movement_type=type,
        variant_id=variant_id,
        product_id=product_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/movements/{id}",
    response_model=InventoryMovementResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener detalle de un movimiento de inventario específico",
)
def get_movement(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.STORE_MANAGER)),
):
    return InventoryMovementService.get_movement(db=db, movement_id=id, user=current_user)


@router.get(
    "/summary/{branch_id}",
    response_model=BranchInventorySummary,
    status_code=status.HTTP_200_OK,
    summary="Resumen de inventario y alertas de stock de una sucursal",
)
def get_branch_summary(
    branch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.STORE_MANAGER, UserRole.CASHIER)),
):
    return InventoryMovementService.get_branch_summary(db=db, branch_id=branch_id)
