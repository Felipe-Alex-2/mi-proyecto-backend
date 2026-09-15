from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.catalog import (
    CatalogFilterOptions,
    CatalogProductDetailResponse,
    CatalogProductListResponse,
)
from app.services.catalog_service import CatalogService

router = APIRouter(prefix="/catalog", tags=["Catalog & Discovery (CU11)"])


@router.get(
    "/filters",
    response_model=CatalogFilterOptions,
    status_code=status.HTTP_200_OK,
    summary="Obtener todas las opciones dinámicas de filtros para el catálogo",
)
def get_catalog_filters(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CatalogService.get_filter_options(db=db)


@router.get(
    "/products",
    response_model=CatalogProductListResponse,
    status_code=status.HTTP_200_OK,
    summary="Listar prendas del catálogo con filtros avanzados y ordenamiento",
)
def list_catalog_products(
    search: Optional[str] = Query(None, description="Búsqueda por texto (nombre, SKU, descripción)"),
    category_id: Optional[str] = Query(None, description="Filtrar por categoría"),
    size_id: Optional[str] = Query(None, description="Filtrar por talla"),
    color_id: Optional[str] = Query(None, description="Filtrar por color"),
    season_id: Optional[str] = Query(None, description="Filtrar por temporada"),
    gender: Optional[str] = Query(None, description="Filtrar por género (Hombre, Mujer, Unisex, Niños)"),
    min_price: Optional[float] = Query(None, ge=0, description="Precio mínimo en Bs"),
    max_price: Optional[float] = Query(None, ge=0, description="Precio máximo en Bs"),
    branch_id: Optional[str] = Query(None, description="Solo prendas con stock en esta sucursal"),
    sort_by: Optional[str] = Query(None, description="Orden: price_asc, price_desc, newest, name_asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CatalogService.list_products(
        db=db,
        search=search,
        category_id=category_id,
        size_id=size_id,
        color_id=color_id,
        season_id=season_id,
        gender=gender,
        min_price=min_price,
        max_price=max_price,
        branch_id=branch_id,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/products/{id}",
    response_model=CatalogProductDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener el detalle de una prenda con disponibilidad por sucursal e indicadores",
)
def get_catalog_product_detail(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CatalogService.get_product(db=db, product_id=id)
