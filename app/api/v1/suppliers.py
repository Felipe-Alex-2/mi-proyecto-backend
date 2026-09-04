from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.supplier import SupplierCreate, SupplierUpdate, SupplierResponse
from app.services.supplier_service import SupplierService
from app.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


@router.get(
    "",
    response_model=List[SupplierResponse],
    status_code=status.HTTP_200_OK,
    summary="List all suppliers",
)
def list_suppliers(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by name, contact, email or phone"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return SupplierService.list_suppliers(db, is_active=is_active, search=search)


@router.post(
    "",
    response_model=SupplierResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create supplier (Admin only)",
)
def create_supplier(
    request: SupplierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return SupplierService.create_supplier(db, request)


@router.get(
    "/{supplier_id}",
    response_model=SupplierResponse,
    status_code=status.HTTP_200_OK,
    summary="Get supplier by ID",
)
def get_supplier(
    supplier_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return SupplierService.get_supplier_by_id(db, supplier_id)


@router.put(
    "/{supplier_id}",
    response_model=SupplierResponse,
    status_code=status.HTTP_200_OK,
    summary="Update supplier (Admin only)",
)
def update_supplier(
    supplier_id: str,
    request: SupplierUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return SupplierService.update_supplier(db, supplier_id, request)


@router.patch(
    "/{supplier_id}/toggle-status",
    response_model=SupplierResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle supplier active status (Admin only)",
)
def toggle_status(
    supplier_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return SupplierService.toggle_status(db, supplier_id)
