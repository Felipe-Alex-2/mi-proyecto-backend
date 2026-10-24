from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.api.dependencias import get_current_user, require_admin, require_roles
from app.base_datos import get_db
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.producto import (
    ProductoCreate,
    ProductoResponse,
    ProductoUpdate,
)
from app.servicios.bitacora_service import BitacoraService
from app.servicios.producto_service import ProductoService
from app.nucleo.ambito_sucursal import resolve_branch

router = APIRouter(prefix="/products", tags=["Products & Garments"])


@router.get(
    "",
    response_model=List[ProductoResponse],
    status_code=status.HTTP_200_OK,
    summary="List all garments/products with optional filters",
)
def list_products(
    category_id: Optional[str] = Query(None, description="Filter by category ID"),
    season_id: Optional[str] = Query(None, description="Filter by season ID"),
    supplier_id: Optional[str] = Query(None, description="Filter by supplier ID"),
    search: Optional[str] = Query(None, description="Search by product name"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    branch_id: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    scope = resolve_branch(current_user, branch_id) if current_user.role != "CUSTOMER" else (db.info.get("customer_branch_id") or branch_id)
    products = ProductoService.list_products(
        db=db,
        category_id=category_id,
        season_id=season_id,
        supplier_id=supplier_id,
        search=search,
        is_active=is_active,
        limit=limit, offset=offset,
    )
    return [_scope_product(product, scope) for product in products]


def _scope_product(product, scope):
    if scope:
        for variant in product.variants:
            variant.stocks = [stock for stock in variant.stocks if stock.branch_id == scope]
            variant.total_stock = sum(stock.quantity for stock in variant.stocks)
        product.total_stock = sum(variant.total_stock for variant in product.variants)
    return product


@router.post(
    "",
    response_model=ProductoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create product with variants and initial stock (Admin only)",
)
def create_product(
    payload: ProductoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    if current_user.role == "STORE_MANAGER":
        scope = resolve_branch(current_user)
        for variant in payload.variants:
            for branch in variant.initial_stock or {}:
                resolve_branch(current_user, branch)
    product = ProductoService.create_product(db, payload)
    BitacoraService.log_event(
        db=db,
        user=current_user,
        action="CREAR_PRODUCTO",
        description=f"Producto creado: {product.name} (ID: {product.id[:8]})",
        category="CATALOGO",
    )
    return _scope_product(ProductoService.get_product_by_id(db, product.id), current_user.branch_id if current_user.role == "STORE_MANAGER" else None)


@router.get(
    "/{product_id}",
    response_model=ProductoResponse,
    status_code=status.HTTP_200_OK,
    summary="Get product detail with variants and stock distribution",
)
def get_product(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    scope = resolve_branch(current_user) if current_user.role in ("STORE_MANAGER", "CASHIER") else None
    return _scope_product(ProductoService.get_product_by_id(db, product_id), scope)


@router.put(
    "/{product_id}",
    response_model=ProductoResponse,
    status_code=status.HTTP_200_OK,
    summary="Update product details (Admin and Store Manager)",
)
def update_product(
    product_id: str,
    payload: ProductoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    if current_user.role == "STORE_MANAGER":
        resolve_branch(current_user)
    updated = ProductoService.update_product(db, product_id, payload)
    BitacoraService.log_event(
        db=db,
        user=current_user,
        action="ACTUALIZAR_PRODUCTO",
        description=f"Producto actualizado: {updated.name} (ID: {updated.id[:8]})",
        category="CATALOGO",
    )
    return _scope_product(updated, current_user.branch_id if current_user.role == "STORE_MANAGER" else None)


@router.patch(
    "/{product_id}/toggle-status",
    response_model=ProductoResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle product active/inactive (Admin and Store Manager)",
)
def toggle_status(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    if current_user.role == "STORE_MANAGER":
        resolve_branch(current_user)
    toggled = ProductoService.toggle_status(db, product_id)
    status_str = "activo" if toggled.is_active else "inactivo"
    BitacoraService.log_event(
        db=db,
        user=current_user,
        action="CAMBIAR_ESTADO_PRODUCTO",
        description=f"Producto {toggled.name} marcado como {status_str}",
        category="CATALOGO",
    )
    return _scope_product(toggled, current_user.branch_id if current_user.role == "STORE_MANAGER" else None)
