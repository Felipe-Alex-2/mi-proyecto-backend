from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.proveedor import ProveedorCreate, ProveedorUpdate, ProveedorResponse
from app.servicios.proveedor_service import ProveedorService
from app.api.dependencias import get_current_user, require_admin, require_roles

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


@router.get(
    "",
    response_model=List[ProveedorResponse],
    status_code=status.HTTP_200_OK,
    summary="List all suppliers",
)
def list_suppliers(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by name, contact, email or phone"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return ProveedorService.list_suppliers(db, is_active=is_active, search=search)


@router.post(
    "",
    response_model=ProveedorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create supplier (Admin and Store Manager)",
)
def create_supplier(
    request: ProveedorCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return ProveedorService.create_supplier(db, request)


@router.get(
    "/{supplier_id}",
    response_model=ProveedorResponse,
    status_code=status.HTTP_200_OK,
    summary="Get supplier by ID",
)
def get_supplier(
    supplier_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return ProveedorService.get_supplier_by_id(db, supplier_id)


@router.put(
    "/{supplier_id}",
    response_model=ProveedorResponse,
    status_code=status.HTTP_200_OK,
    summary="Update supplier (Admin and Store Manager)",
)
def update_supplier(
    supplier_id: str,
    request: ProveedorUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return ProveedorService.update_supplier(db, supplier_id, request)


@router.patch(
    "/{supplier_id}/toggle-status",
    response_model=ProveedorResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle supplier active status (Admin and Store Manager)",
)
def toggle_status(
    supplier_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return ProveedorService.toggle_status(db, supplier_id)
