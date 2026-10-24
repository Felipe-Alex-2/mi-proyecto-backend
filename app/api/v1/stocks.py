from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.api.dependencias import get_current_user, require_admin, require_roles
from app.base_datos import get_db
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.stock import (
    InventarioSucursalItem,
    AjusteStockRequest,
    StockResponse,
)
from app.esquemas.movimiento_inventario import DisponibilidadVarianteSucursal
from app.servicios.stock_service import StockService
from app.nucleo.ambito_sucursal import resolve_branch

router = APIRouter(prefix="/stocks", tags=["Stock & Inventory (CU10)"])


@router.get(
    "/branch/{branch_id}",
    response_model=List[InventarioSucursalItem],
    status_code=status.HTTP_200_OK,
    summary="Get branch inventory items with low stock indicators",
)
def get_branch_inventory(
    branch_id: str,
    search: Optional[str] = Query(None, description="Search by product name or SKU"),
    low_stock_only: bool = Query(False, description="Filter only low stock items"),
    limit: Optional[int] = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if current_user.role in ("STORE_MANAGER", "CASHIER"):
        resolve_branch(current_user, branch_id)
    return StockService.get_branch_inventory(
        db=db,
        branch_id=branch_id,
        search=search,
        low_stock_only=low_stock_only,
        limit=limit, offset=offset,
    )


@router.get(
    "/variant/{variant_id}/availability",
    response_model=List[DisponibilidadVarianteSucursal],
    status_code=status.HTTP_200_OK,
    summary="Consultar disponibilidad de una variante en todas las sucursales con indicadores",
)
def get_variant_availability(
    variant_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    items = StockService.get_variant_availability(db=db, variant_id=variant_id)
    if current_user.role in ("STORE_MANAGER", "CASHIER"):
        scope = resolve_branch(current_user)
        items = [item for item in items if item.branch_id == scope]
    return items


@router.get(
    "/matrix",
    response_model=List[Dict[str, Any]],
    status_code=status.HTTP_200_OK,
    summary="Matriz de disponibilidad cruzada de variantes por sucursal (Admin / Staff)",
)
def get_availability_matrix(
    product_id: Optional[str] = Query(None, description="Filtrar por ID de producto"),
    branch_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER, RolUsuario.CASHIER)),
):
    return StockService.get_availability_matrix(db=db, product_id=product_id, branch_id=resolve_branch(current_user, branch_id))


@router.post(
    "/adjust",
    response_model=StockResponse,
    status_code=status.HTTP_200_OK,
    summary="Adjust variant stock quantity in branch (Admin/Store Manager)",
)
def adjust_stock(
    payload: AjusteStockRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    resolve_branch(current_user, payload.branch_id)
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
