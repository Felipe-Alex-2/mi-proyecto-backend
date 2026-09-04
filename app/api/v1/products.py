from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.user import User
from app.schemas.product import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)
from app.services.product_service import ProductService

router = APIRouter(prefix="/products", tags=["Products & Garments"])


@router.get(
    "",
    response_model=List[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="List all garments/products with optional filters",
)
def list_products(
    category_id: Optional[str] = Query(None, description="Filter by category ID"),
    season_id: Optional[str] = Query(None, description="Filter by season ID"),
    supplier_id: Optional[str] = Query(None, description="Filter by supplier ID"),
    search: Optional[str] = Query(None, description="Search by product name"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ProductService.list_products(
        db=db,
        category_id=category_id,
        season_id=season_id,
        supplier_id=supplier_id,
        search=search,
        is_active=is_active,
    )


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create product with variants and initial stock (Admin only)",
)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    product = ProductService.create_product(db, payload)
    return ProductService.get_product_by_id(db, product.id)


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Get product detail with variants and stock distribution",
)
def get_product(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ProductService.get_product_by_id(db, product_id)


@router.put(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Update product details (Admin only)",
)
def update_product(
    product_id: str,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return ProductService.update_product(db, product_id, payload)


@router.patch(
    "/{product_id}/toggle-status",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle product active/inactive (Admin only)",
)
def toggle_status(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return ProductService.toggle_status(db, product_id)
