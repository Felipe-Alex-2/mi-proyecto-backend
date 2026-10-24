from app.nucleo.transacciones import commit_or_flush
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.modelos.sucursal import Sucursal
from app.modelos.categoria import Categoria
from app.modelos.color import Color
from app.modelos.producto import Producto
from app.modelos.variante_producto import VarianteProducto
from app.modelos.temporada import Temporada
from app.modelos.promocion import Promocion
from app.modelos.talla import Talla
from app.modelos.stock import Stock
from app.modelos.proveedor import Proveedor
from app.esquemas.producto import (
    ProductoCreate,
    ProductoResponse,
    ProductoUpdate,
    VarianteProductoResponse,
)
from app.esquemas.stock import StockResponse
from app.servicios.carga_productos import product_load_options


class ProductoService:
    @staticmethod
    def _generate_sku(product_name: str, size_code: str, color_name: str, db: Session) -> str:
        clean_name = re.sub(r"[^A-Za-z0-9]", "", product_name)[:3].upper()
        clean_size = re.sub(r"[^A-Za-z0-9]", "", size_code)[:3].upper()
        clean_color = re.sub(r"[^A-Za-z0-9]", "", color_name)[:3].upper()
        base_sku = f"{clean_name}-{clean_color}-{clean_size}"

        sku = base_sku
        counter = 1
        while db.query(VarianteProducto).filter(func.lower(VarianteProducto.sku) == sku.lower()).first():
            sku = f"{base_sku}-{counter}"
            counter += 1
        return sku

    @staticmethod
    def create_product(db: Session, payload: ProductoCreate) -> Producto:
        clean_name = payload.name.strip()
        existing_product = db.query(Producto).filter(func.lower(Producto.name) == clean_name.lower()).first()
        if existing_product:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe una prenda con el nombre '{clean_name}'"
            )

        category = db.query(Categoria).filter(Categoria.id == payload.category_id).first()
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La categoría especificada no existe"
            )

        if payload.season_id:
            season = db.query(Temporada).filter(Temporada.id == payload.season_id).first()
            if not season:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="La temporada especificada no existe"
                )

        if payload.supplier_id:
            supplier = db.query(Proveedor).filter(Proveedor.id == payload.supplier_id).first()
            if not supplier:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="El proveedor especificado no existe"
                )

        if payload.promotion_id:
            promotion = db.query(Promocion).filter(Promocion.id == payload.promotion_id).first()
            if not promotion:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="La promoción especificada no existe"
                )

        branch_ids = {branch_id for variant in payload.variants for branch_id in (variant.initial_stock or {})}
        if branch_ids:
            known_branches = {row[0] for row in db.query(Sucursal.id).filter(Sucursal.id.in_(branch_ids)).all()}
            if branch_ids - known_branches:
                raise HTTPException(status_code=404, detail='Una sucursal del stock inicial no existe')

        product = Producto(
            name=clean_name,
            description=payload.description.strip() if payload.description else None,
            price=payload.price,
            category_id=payload.category_id,
            season_id=payload.season_id,
            supplier_id=payload.supplier_id,
            promotion_id=payload.promotion_id if payload.promotion_id else None,
            image_url=payload.image_url.strip() if payload.image_url else None,
            gender=payload.gender.upper() if payload.gender else "UNISEX",
            is_active=True,
        )
        db.add(product)
        db.flush()

        for variant_data in payload.variants:
            size = db.query(Talla).filter(Talla.id == variant_data.size_id).first()
            if not size:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Talla con ID '{variant_data.size_id}' no encontrada"
                )

            color = db.query(Color).filter(Color.id == variant_data.color_id).first()
            if not color:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Color con ID '{variant_data.color_id}' no encontrado"
                )

            sku = variant_data.sku
            if not sku:
                sku = ProductoService._generate_sku(product.name, size.code, color.name, db)
            else:
                existing_sku = db.query(VarianteProducto).filter(func.lower(VarianteProducto.sku) == sku.lower()).first()
                if existing_sku:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"El SKU '{sku}' ya está en uso"
                    )

            variant = VarianteProducto(
                product_id=product.id,
                size_id=variant_data.size_id,
                color_id=variant_data.color_id,
                sku=sku,
                price_override=variant_data.price_override,
            )
            db.add(variant)
            db.flush()

            if variant_data.initial_stock:
                for branch_id, quantity in variant_data.initial_stock.items():
                    if quantity > 0:
                        stock = Stock(
                            variant_id=variant.id,
                            branch_id=branch_id,
                            quantity=quantity,
                        )
                        db.add(stock)

        commit_or_flush(db)
        db.refresh(product)
        return product

    @staticmethod
    def _map_product_response(product: Producto) -> ProductoResponse:
        variants_resp: List[VarianteProductoResponse] = []
        product_total_stock = 0

        for v in product.variants:
            var_stock = sum(s.quantity for s in v.stocks)
            product_total_stock += var_stock

            stock_items = [
                StockResponse(
                    id=s.id,
                    variant_id=s.variant_id,
                    branch_id=s.branch_id,
                    quantity=s.quantity,
                    min_alert_threshold=s.min_alert_threshold,
                    updated_at=s.updated_at,
                    branch_name=s.branch.name if s.branch else None,
                    branch_city=s.branch.city if s.branch else None,
                )
                for s in v.stocks
            ]

            variants_resp.append(
                VarianteProductoResponse(
                    id=v.id,
                    product_id=v.product_id,
                    size_id=v.size_id,
                    color_id=v.color_id,
                    sku=v.sku,
                    price_override=float(v.price_override) if v.price_override is not None else None,
                    is_active=v.is_active,
                    size_code=v.size.code if v.size else None,
                    size_name=v.size.name if v.size else None,
                    color_name=v.color.name if v.color else None,
                    color_hex=v.color.hex_code if v.color else None,
                    total_stock=var_stock,
                    stocks=stock_items,
                )
            )

        return ProductoResponse(
            id=product.id,
            name=product.name,
            description=product.description,
            price=float(product.price),
            category_id=product.category_id,
            category_name=product.category.name if product.category else None,
            season_id=product.season_id,
            season_name=product.season.name if product.season else None,
            supplier_id=product.supplier_id,
            supplier_name=product.supplier.company_name if product.supplier else None,
            promotion_id=product.promotion_id,
            promotion_name=product.promotion.name if (product.promotion and product.promotion.is_active) else None,
            discount_percent=float(product.promotion.discount_percent) if (product.promotion and product.promotion.is_active) else None,
            image_url=product.image_url,
            gender=product.gender,
            is_active=product.is_active,
            total_stock=product_total_stock,
            variants=variants_resp,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )

    @staticmethod
    def list_products(
        db: Session,
        category_id: Optional[str] = None,
        season_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        search: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[ProductoResponse]:
        query = db.query(Producto).options(*product_load_options())
        if db.info.get('customer_branch_id'):
            query = query.filter(Producto.variants.any(VarianteProducto.stocks.any(Stock.branch_id == db.info['customer_branch_id'])))

        if category_id:
            query = query.filter(Producto.category_id == category_id)
        if season_id:
            query = query.filter(Producto.season_id == season_id)
        if supplier_id:
            query = query.filter(Producto.supplier_id == supplier_id)
        if is_active is not None:
            query = query.filter(Producto.is_active == is_active)
        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.filter(Producto.name.ilike(pattern))

        query = query.order_by(Producto.created_at.desc(), Producto.id).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        products = query.all()
        return [ProductoService._map_product_response(p) for p in products]

    @staticmethod
    def get_product_by_id(db: Session, product_id: str) -> ProductoResponse:
        product = db.query(Producto).options(*product_load_options()).filter(Producto.id == product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prenda no encontrada"
            )
        return ProductoService._map_product_response(product)

    @staticmethod
    def update_product(db: Session, product_id: str, payload: ProductoUpdate) -> ProductoResponse:
        product = db.query(Producto).filter(Producto.id == product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prenda no encontrada"
            )

        if payload.name is not None:
            clean_name = payload.name.strip()
            if clean_name.lower() != product.name.lower():
                existing = db.query(Producto).filter(
                    func.lower(Producto.name) == clean_name.lower(),
                    Producto.id != product.id
                ).first()
                if existing:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Ya existe otra prenda con el nombre '{clean_name}'"
                    )
            product.name = clean_name

        if "description" in payload.model_fields_set:
            product.description = payload.description.strip() if payload.description else None
        if payload.price is not None:
            product.price = payload.price
        if payload.category_id is not None:
            cat = db.query(Categoria).filter(Categoria.id == payload.category_id).first()
            if not cat:
                raise HTTPException(status_code=404, detail="Categoría no encontrada")
            product.category_id = payload.category_id
        if "season_id" in payload.model_fields_set:
            if payload.season_id:
                seas = db.query(Temporada).filter(Temporada.id == payload.season_id).first()
                if not seas:
                    raise HTTPException(status_code=404, detail="Temporada no encontrada")
            product.season_id = payload.season_id if payload.season_id else None
        if "supplier_id" in payload.model_fields_set:
            if payload.supplier_id:
                sup = db.query(Proveedor).filter(Proveedor.id == payload.supplier_id).first()
                if not sup:
                    raise HTTPException(status_code=404, detail="Proveedor no encontrado")
            product.supplier_id = payload.supplier_id if payload.supplier_id else None
        if "promotion_id" in payload.model_fields_set:
            if payload.promotion_id:
                promo = db.query(Promocion).filter(Promocion.id == payload.promotion_id).first()
                if not promo:
                    raise HTTPException(status_code=404, detail="Promoción no encontrada")
            product.promotion_id = payload.promotion_id if payload.promotion_id else None
        if "image_url" in payload.model_fields_set:
            product.image_url = payload.image_url.strip() if payload.image_url else None
        if payload.gender is not None:
            product.gender = payload.gender.upper()
        if payload.is_active is not None:
            product.is_active = payload.is_active

        product.updated_at = datetime.now(timezone.utc)
        commit_or_flush(db)
        db.refresh(product)
        return ProductoService._map_product_response(product)

    @staticmethod
    def toggle_status(db: Session, product_id: str) -> ProductoResponse:
        product = db.query(Producto).filter(Producto.id == product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prenda no encontrada"
            )
        product.is_active = not product.is_active
        product.updated_at = datetime.now(timezone.utc)
        commit_or_flush(db)
        db.refresh(product)
        return ProductoService._map_product_response(product)
