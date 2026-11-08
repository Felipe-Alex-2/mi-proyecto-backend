from app.nucleo.transacciones import commit_or_flush
from typing import List
from sqlalchemy.orm import Session, joinedload
from app.modelos.carrito_item import CarritoItem
from app.modelos.variante_producto import VarianteProducto
from app.modelos.producto import Producto
from app.modelos.stock import Stock
from app.esquemas.carrito import (
    CarritoItemAdd,
    CarritoItemUpdate,
    CarritoItemResponse,
    CarritoResponse,
)
from app.nucleo.excepciones import NoEncontradoException, SolicitudInvalidaException


class CarritoService:
    @classmethod
    def get_cart(cls, db: Session, user_id: str) -> CarritoResponse:
        items = db.query(CarritoItem).options(
            joinedload(CarritoItem.variant).joinedload(VarianteProducto.product).joinedload(Producto.promotion),
            joinedload(CarritoItem.variant).joinedload(VarianteProducto.size),
            joinedload(CarritoItem.variant).joinedload(VarianteProducto.color),
            joinedload(CarritoItem.variant).selectinload(VarianteProducto.stocks),
        ).filter(CarritoItem.user_id == user_id).order_by(CarritoItem.added_at.desc()).all()
        response_items: List[CarritoItemResponse] = []
        total_items = 0
        total_amount = 0.0

        for item in items:
            v = item.variant
            if not v:
                continue

            from app.servicios.aporte_propio_service import price as effective_price
            original_price = float(v.price_override if v.price_override is not None else v.product.price)
            price = float(effective_price(v))
            discount_percent = round((1-price/original_price)*100, 2) if original_price and price < original_price else None

            subtotal = round(price * item.quantity, 2)
            total_items += item.quantity
            total_amount += subtotal

            # Total stock across all branches for this variant
            available_stock = sum(s.quantity for s in v.stocks)

            resp_item = CarritoItemResponse(
                id=item.id,
                variant_id=item.variant_id,
                quantity=item.quantity,
                added_at=item.added_at,
                updated_at=item.updated_at,
                product_id=v.product_id,
                product_name=v.product.name if v.product else None,
                sku=v.sku,
                size_name=v.size.name if v.size else None,
                color_name=v.color.name if v.color else None,
                color_hex=v.color.hex_code if v.color else None,
                price=price,
                original_price=original_price if (discount_percent and discount_percent > 0) else None,
                discount_percent=discount_percent,
                subtotal=subtotal,
                image_url=v.product.image_url if v.product else None,
                available_stock=available_stock,
            )
            response_items.append(resp_item)

        from app.servicios.venta_mayor_service import summary
        totals = summary(total_amount, total_items)
        return CarritoResponse(
            **totals,
            items=response_items,
            total_items=total_items,
        )

    @classmethod
    def add_item(cls, db: Session, user_id: str, data: CarritoItemAdd) -> CarritoResponse:
        variant = db.query(VarianteProducto).filter(VarianteProducto.id == data.variant_id).first()
        if not variant:
            raise NoEncontradoException(detail="Variante de producto no encontrada")

        if variant.product and not variant.product.is_active:
            raise SolicitudInvalidaException(detail="El producto se encuentra inactivo")

        existing_item = (
            db.query(CarritoItem)
            .filter(CarritoItem.user_id == user_id, CarritoItem.variant_id == data.variant_id)
            .first()
        )

        if existing_item:
            existing_item.quantity += data.quantity
        else:
            new_item = CarritoItem(
                user_id=user_id,
                variant_id=data.variant_id,
                quantity=data.quantity,
                branch_id=db.info.get("customer_branch_id"),
            )
            db.add(new_item)

        commit_or_flush(db)
        return cls.get_cart(db, user_id)

    @classmethod
    def update_item_quantity(
        cls, db: Session, user_id: str, item_id: str, data: CarritoItemUpdate
    ) -> CarritoResponse:
        item = db.query(CarritoItem).filter(CarritoItem.id == item_id, CarritoItem.user_id == user_id).first()
        if not item:
            raise NoEncontradoException(detail="Item del carrito no encontrado")

        item.quantity = data.quantity
        commit_or_flush(db)
        return cls.get_cart(db, user_id)

    @classmethod
    def remove_item(cls, db: Session, user_id: str, item_id: str) -> CarritoResponse:
        item = db.query(CarritoItem).filter(CarritoItem.id == item_id, CarritoItem.user_id == user_id).first()
        if not item:
            raise NoEncontradoException(detail="Item del carrito no encontrado")

        db.delete(item)
        commit_or_flush(db)
        return cls.get_cart(db, user_id)

    @classmethod
    def clear_cart(cls, db: Session, user_id: str) -> CarritoResponse:
        db.query(CarritoItem).filter(CarritoItem.user_id == user_id).delete()
        commit_or_flush(db)
        return CarritoResponse(items=[], total_items=0, total_amount=0.0)
