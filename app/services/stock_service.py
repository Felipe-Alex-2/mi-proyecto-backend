from datetime import datetime, timezone
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.branch import Branch
from app.models.category import Category
from app.models.color import Color
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.size import Size
from app.models.stock import Stock
from app.schemas.stock import BranchInventoryItem, StockAdjustRequest


class StockService:
    @staticmethod
    def adjust_stock(db: Session, request: StockAdjustRequest) -> Stock:
        variant = db.query(ProductVariant).filter(ProductVariant.id == request.variant_id).first()
        if not variant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Variante de producto no encontrada"
            )

        branch = db.query(Branch).filter(Branch.id == request.branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sucursal no encontrada"
            )

        stock = db.query(Stock).filter(
            Stock.variant_id == request.variant_id,
            Stock.branch_id == request.branch_id
        ).first()

        if stock:
            stock.quantity = request.quantity
            stock.updated_at = datetime.now(timezone.utc)
        else:
            stock = Stock(
                variant_id=request.variant_id,
                branch_id=request.branch_id,
                quantity=request.quantity,
            )
            db.add(stock)

        db.commit()
        db.refresh(stock)
        return stock

    @staticmethod
    def get_branch_inventory(
        db: Session,
        branch_id: str,
        search: Optional[str] = None,
        low_stock_only: bool = False
    ) -> List[BranchInventoryItem]:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sucursal no encontrada"
            )

        query = (
            db.query(Stock, ProductVariant, Product, Size, Color, Category)
            .join(ProductVariant, Stock.variant_id == ProductVariant.id)
            .join(Product, ProductVariant.product_id == Product.id)
            .join(Size, ProductVariant.size_id == Size.id)
            .join(Color, ProductVariant.color_id == Color.id)
            .join(Category, Product.category_id == Category.id)
            .filter(Stock.branch_id == branch_id)
        )

        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.filter(
                (Product.name.ilike(pattern)) | (ProductVariant.sku.ilike(pattern))
            )

        if low_stock_only:
            query = query.filter(Stock.quantity <= Stock.min_alert_threshold)

        results = query.all()
        items: List[BranchInventoryItem] = []

        for stock, variant, product, size, color, category in results:
            items.append(
                BranchInventoryItem(
                    variant_id=variant.id,
                    product_id=product.id,
                    product_name=product.name,
                    category_name=category.name,
                    sku=variant.sku,
                    size_code=size.code,
                    size_name=size.name,
                    color_name=color.name,
                    color_hex=color.hex_code,
                    price=float(variant.price_override if variant.price_override is not None else product.price),
                    quantity=stock.quantity,
                    min_alert_threshold=stock.min_alert_threshold,
                    is_low_stock=stock.quantity <= stock.min_alert_threshold,
                )
            )

        return items
