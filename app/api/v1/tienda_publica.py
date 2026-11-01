"""Read-only storefront. Resolve and validate its company before every query."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.modelos.saas import Empresa
from app.modelos.sucursal import Sucursal
from app.esquemas.catalogo import OpcionesFiltroCatalogo, ListaProductosCatalogoResponse, DetalleProductoCatalogoResponse
from app.servicios.catalogo_service import CatalogoService
from app.servicios.saas_service import enforce_subscription

router = APIRouter(prefix='/shop/catalog', tags=['Tienda pública'])


def public_store(tenant_id: str = Query(...), store_branch: str = Query(...), db: Session = Depends(get_db)):
    company = db.query(Empresa).execution_options(skip_tenant=True).filter(Empresa.id == tenant_id, Empresa.is_active == True).first()
    branch = db.query(Sucursal).execution_options(skip_tenant=True).filter(
        Sucursal.id == store_branch, Sucursal.tenant_id == tenant_id, Sucursal.is_active == True).first()
    if not company or not branch:
        raise HTTPException(404, 'La tienda o sucursal no está disponible.')
    db.info.update(tenant_context=True, tenant_id=tenant_id, customer_branch_id=store_branch,
                   personal_history=False, actor_id=None)
    enforce_subscription(db, tenant_id, write=False)
    return db


@router.get('/filters', response_model=OpcionesFiltroCatalogo)
def filters(db: Session = Depends(public_store)):
    result = CatalogoService.get_filter_options(db)
    result.branches = [b for b in result.branches if b['id'] == db.info['customer_branch_id']]
    return result


@router.get('/products', response_model=ListaProductosCatalogoResponse)
def products(search: Optional[str] = None, category_id: Optional[str] = None,
             size_id: Optional[str] = None, color_id: Optional[str] = None,
             season_id: Optional[str] = None, gender: Optional[str] = None,
             min_price: Optional[float] = Query(None, ge=0), max_price: Optional[float] = Query(None, ge=0),
             sort_by: Optional[str] = None, page: int = Query(1, ge=1),
             page_size: int = Query(20, ge=1, le=100), db: Session = Depends(public_store)):
    return CatalogoService.list_products(db, search=search, category_id=category_id, size_id=size_id,
        color_id=color_id, season_id=season_id, gender=gender, min_price=min_price,
        max_price=max_price, sort_by=sort_by, page=page, page_size=page_size)


@router.get('/products/{product_id}', response_model=DetalleProductoCatalogoResponse)
def product(product_id: str, db: Session = Depends(public_store)):
    return CatalogoService.get_product(db, product_id)
