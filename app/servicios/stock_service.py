from app.nucleo.transacciones import commit_or_flush
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.modelos.sucursal import Sucursal
from app.modelos.categoria import Categoria
from app.modelos.color import Color
from app.modelos.producto import Producto
from app.modelos.variante_producto import VarianteProducto
from app.modelos.talla import Talla
from app.modelos.stock import Stock
from app.esquemas.stock import InventarioSucursalItem, AjusteStockRequest
from app.esquemas.movimiento_inventario import DisponibilidadVarianteSucursal


class StockService:
    @staticmethod
    def adjust_stock(db: Session, request: AjusteStockRequest) -> Stock:
        variant = db.query(VarianteProducto).filter(VarianteProducto.id == request.variant_id).first()
        if not variant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Variante de producto no encontrada"
            )

        branch = db.query(Sucursal).filter(Sucursal.id == request.branch_id).first()
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

        commit_or_flush(db)
        db.refresh(stock)
        return stock

    @staticmethod
    def get_branch_inventory(
        db: Session,
        branch_id: str,
        search: Optional[str] = None,
        low_stock_only: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[InventarioSucursalItem]:
        branch = db.query(Sucursal).filter(Sucursal.id == branch_id).first()
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sucursal no encontrada"
            )

        query = (
            db.query(Stock, VarianteProducto, Producto, Talla, Color, Categoria)
            .join(VarianteProducto, Stock.variant_id == VarianteProducto.id)
            .join(Producto, VarianteProducto.product_id == Producto.id)
            .join(Talla, VarianteProducto.size_id == Talla.id)
            .join(Color, VarianteProducto.color_id == Color.id)
            .join(Categoria, Producto.category_id == Categoria.id)
            .filter(Stock.branch_id == branch_id)
        )

        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.filter(
                (Producto.name.ilike(pattern)) | (VarianteProducto.sku.ilike(pattern))
            )

        if low_stock_only:
            query = query.filter(Stock.quantity <= Stock.min_alert_threshold)

        query = query.order_by(Stock.id).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        results = query.all()
        items: List[InventarioSucursalItem] = []

        for stock, variant, product, size, color, category in results:
            base_p = float(variant.price_override if variant.price_override is not None else product.price)
            disc_pct = (
                float(product.promotion.discount_percent)
                if (product.promotion and product.promotion.is_active and product.promotion.discount_percent)
                else None
            )
            eff_price = round(base_p * (1.0 - disc_pct / 100.0), 2) if (disc_pct and disc_pct > 0) else base_p

            items.append(
                InventarioSucursalItem(
                    variant_id=variant.id,
                    product_id=product.id,
                    product_name=product.name,
                    category_name=category.name,
                    sku=variant.sku,
                    size_code=size.code,
                    size_name=size.name,
                    color_name=color.name,
                    color_hex=color.hex_code,
                    price=eff_price,
                    original_price=base_p if (disc_pct and disc_pct > 0) else None,
                    discount_percent=disc_pct,
                    quantity=stock.quantity,
                    min_alert_threshold=stock.min_alert_threshold,
                    is_low_stock=stock.quantity <= stock.min_alert_threshold,
                )
            )

        return items

    @staticmethod
    def get_variant_availability(db: Session, variant_id: str) -> List[DisponibilidadVarianteSucursal]:
        variant = db.query(VarianteProducto).filter(VarianteProducto.id == variant_id).first()
        if not variant:
            raise HTTPException(status_code=404, detail="Variante no encontrada")

        branches = db.query(Sucursal).filter(Sucursal.is_active == True).order_by(Sucursal.name.asc()).all()
        stocks_map = {s.branch_id: s for s in db.query(Stock).filter(Stock.variant_id == variant_id).all()}

        results = []
        for b in branches:
            stk = stocks_map.get(b.id)
            qty = stk.quantity if stk else 0
            threshold = stk.min_alert_threshold if stk else 5
            if qty <= 0:
                st = "OUT_OF_STOCK"
            elif qty <= threshold:
                st = "LOW_STOCK"
            else:
                st = "IN_STOCK"

            results.append(
                DisponibilidadVarianteSucursal(
                    branch_id=b.id,
                    branch_name=b.name,
                    branch_city=b.city,
                    branch_address=b.address,
                    quantity=qty,
                    status=st,
                )
            )
        return results

    @staticmethod
    def get_availability_matrix(db: Session, product_id: Optional[str] = None, branch_id: Optional[str] = None) -> List[Dict[str, Any]]:
        branch_query = db.query(Sucursal).filter(Sucursal.is_active == True)
        if branch_id:
            branch_query = branch_query.filter(Sucursal.id == branch_id)
        branches = branch_query.order_by(Sucursal.name.asc()).all()
        query = (
            db.query(VarianteProducto, Producto, Talla, Color)
            .join(Producto, VarianteProducto.product_id == Producto.id)
            .join(Talla, VarianteProducto.size_id == Talla.id)
            .join(Color, VarianteProducto.color_id == Color.id)
            .filter(Producto.is_active == True)
        )
        if product_id:
            query = query.filter(Producto.id == product_id)

        rows = query.order_by(Producto.name.asc(), Talla.name.asc()).all()
        matrix = []
        stock_query = db.query(Stock)
        if branch_id:
            stock_query = stock_query.filter(Stock.branch_id == branch_id)
        stocks_by_variant = {}
        for stock in stock_query.all():
            stocks_by_variant.setdefault(stock.variant_id, {})[stock.branch_id] = stock.quantity

        for variant, product, size, color in rows:
            stocks_map = stocks_by_variant.get(variant.id, {})
            branch_data = {}
            total_qty = 0
            for b in branches:
                q = stocks_map.get(b.id, 0)
                branch_data[b.id] = q
                total_qty += q

            matrix.append({
                "variant_id": variant.id,
                "product_id": product.id,
                "product_name": product.name,
                "sku": variant.sku,
                "size_name": size.name,
                "size_code": size.code,
                "color_name": color.name,
                "color_hex": color.hex_code,
                "price": float(product.price),
                "total_quantity": total_qty,
                "branches": branch_data,
            })
        return matrix
