from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_admin, require_roles
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.stock import (
    BranchInventoryItem,
    StockAdjustRequest,
    StockResponse,
)
from app.schemas.inventory_movement import VariantBranchAvailability
from app.services.stock_service import StockService

router = APIRouter(prefix="/stocks", tags=["Stock & Inventory (CU10)"])


@router.get(
    "/branch/{branch_id}",
    response_model=List[BranchInventoryItem],
    status_code=status.HTTP_200_OK,
    summary="Get branch inventory items with low stock indicators",
)
def get_branch_inventory(
    branch_id: str,
    search: Optional[str] = Query(None, description="Search by product name or SKU"),
    low_stock_only: bool = Query(False, description="Filter only low stock items"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return StockService.get_branch_inventory(
        db=db,
        branch_id=branch_id,
        search=search,
        low_stock_only=low_stock_only,
    )


@router.get(
    "/variant/{variant_id}/availability",
    response_model=List[VariantBranchAvailability],
    status_code=status.HTTP_200_OK,
    summary="Consultar disponibilidad de una variante en todas las sucursales con indicadores",
)
def get_variant_availability(
    variant_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return StockService.get_variant_availability(db=db, variant_id=variant_id)


@router.get(
    "/matrix",
    response_model=List[Dict[str, Any]],
    status_code=status.HTTP_200_OK,
    summary="Matriz de disponibilidad cruzada de variantes por sucursal (Admin / Staff)",
)
def get_availability_matrix(
    product_id: Optional[str] = Query(None, description="Filtrar por ID de producto"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.STORE_MANAGER, UserRole.CASHIER)),
):
    return StockService.get_availability_matrix(db=db, product_id=product_id)


@router.post(
    "/adjust",
    response_model=StockResponse,
    status_code=status.HTTP_200_OK,
    summary="Adjust variant stock quantity in branch (Admin/Store Manager)",
)
def adjust_stock(
    payload: StockAdjustRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    stock = StockService.adjust_stock(db, payload)
    return StockResponse(
        id=stock.id,
        variant_id=stock.variant_id,
        branch_id=stock.branch_id,
        quantity=stock.quantity,
        min_alert_threshold=stock.min_alert_threshold,
        updated_at=stock.updated_at,
        branch_name=stock.branch.name if stock.branch else None,
        branch_city=stock.branch.city if stock.branch else None,
    )
