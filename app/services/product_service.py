import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.category import Category
from app.models.color import Color
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.season import Season
from app.models.size import Size
from app.models.stock import Stock
from app.models.supplier import Supplier
from app.schemas.product import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    ProductVariantResponse,
)
from app.schemas.stock import StockResponse


class ProductService:
    @staticmethod
    def _generate_sku(product_name: str, size_code: str, color_name: str, db: Session) -> str:
        clean_name = re.sub(r"[^A-Za-z0-9]", "", product_name)[:3].upper()
        clean_size = re.sub(r"[^A-Za-z0-9]", "", size_code)[:3].upper()
        clean_color = re.sub(r"[^A-Za-z0-9]", "", color_name)[:3].upper()
        base_sku = f"{clean_name}-{clean_color}-{clean_size}"

        sku = base_sku
        counter = 1
        while db.query(ProductVariant).filter(ProductVariant.sku == sku).first():
            sku = f"{base_sku}-{counter}"
            counter += 1
        return sku

    @staticmethod
    def create_product(db: Session, payload: ProductCreate) -> Product:
        category = db.query(Category).filter(Category.id == payload.category_id).first()
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La categoría especificada no existe"
            )

        if payload.season_id:
            season = db.query(Season).filter(Season.id == payload.season_id).first()
            if not season:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="La temporada especificada no existe"
                )

        if payload.supplier_id:
            supplier = db.query(Supplier).filter(Supplier.id == payload.supplier_id).first()
            if not supplier:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="El proveedor especificado no existe"
                )

        product = Product(
            name=payload.name.strip(),
            description=payload.description.strip() if payload.description else None,
            price=payload.price,
            category_id=payload.category_id,
            season_id=payload.season_id,
            supplier_id=payload.supplier_id,
            image_url=payload.image_url.strip() if payload.image_url else None,
            gender=payload.gender.upper(),
        )
        db.add(product)
        db.flush()

        seen_combinations = set()
        for variant_data in payload.variants:
            combo_key = (variant_data.size_id, variant_data.color_id)
            if combo_key in seen_combinations:
                continue
            seen_combinations.add(combo_key)

            size = db.query(Size).filter(Size.id == variant_data.size_id).first()
            if not size:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Talla con ID {variant_data.size_id} no encontrada"
                )

            color = db.query(Color).filter(Color.id == variant_data.color_id).first()
            if not color:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Color con ID {variant_data.color_id} no encontrado"
                )

            sku = variant_data.sku
            if not sku:
                sku = ProductService._generate_sku(product.name, size.code, color.name, db)
            else:
                existing_sku = db.query(ProductVariant).filter(ProductVariant.sku == sku).first()
                if existing_sku:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"El SKU '{sku}' ya está en uso"
                    )

            variant = ProductVariant(
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

        db.commit()
        db.refresh(product)
        return product

    @staticmethod
    def _map_product_response(product: Product) -> ProductResponse:
        variants_resp: List[ProductVariantResponse] = []
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
                ProductVariantResponse(
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

        return ProductResponse(
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
    ) -> List[ProductResponse]:
        query = db.query(Product)

        if category_id:
            query = query.filter(Product.category_id == category_id)
        if season_id:
            query = query.filter(Product.season_id == season_id)
        if supplier_id:
            query = query.filter(Product.supplier_id == supplier_id)
        if is_active is not None:
            query = query.filter(Product.is_active == is_active)
        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.filter(Product.name.ilike(pattern))

        products = query.order_by(Product.created_at.desc()).all()
        return [ProductService._map_product_response(p) for p in products]

    @staticmethod
    def get_product_by_id(db: Session, product_id: str) -> ProductResponse:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prenda no encontrada"
            )
        return ProductService._map_product_response(product)

    @staticmethod
    def update_product(db: Session, product_id: str, payload: ProductUpdate) -> ProductResponse:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prenda no encontrada"
            )

        if payload.name is not None:
            product.name = payload.name.strip()
        if payload.description is not None:
            product.description = payload.description.strip() if payload.description else None
        if payload.price is not None:
            product.price = payload.price
        if payload.category_id is not None:
            cat = db.query(Category).filter(Category.id == payload.category_id).first()
            if not cat:
                raise HTTPException(status_code=404, detail="Categoría no encontrada")
            product.category_id = payload.category_id
        if payload.season_id is not None:
            if payload.season_id:
                seas = db.query(Season).filter(Season.id == payload.season_id).first()
                if not seas:
                    raise HTTPException(status_code=404, detail="Temporada no encontrada")
            product.season_id = payload.season_id if payload.season_id else None
        if payload.supplier_id is not None:
            if payload.supplier_id:
                sup = db.query(Supplier).filter(Supplier.id == payload.supplier_id).first()
                if not sup:
                    raise HTTPException(status_code=404, detail="Proveedor no encontrado")
            product.supplier_id = payload.supplier_id if payload.supplier_id else None
        if payload.image_url is not None:
            product.image_url = payload.image_url.strip() if payload.image_url else None
        if payload.gender is not None:
            product.gender = payload.gender.upper()
        if payload.is_active is not None:
            product.is_active = payload.is_active

        product.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(product)
        return ProductService._map_product_response(product)

    @staticmethod
    def toggle_status(db: Session, product_id: str) -> ProductResponse:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prenda no encontrada"
            )
        product.is_active = not product.is_active
        product.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(product)
        return ProductService._map_product_response(product)
