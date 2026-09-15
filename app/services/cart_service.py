from typing import List
from sqlalchemy.orm import Session
from app.models.cart_item import CartItem
from app.models.product_variant import ProductVariant
from app.models.product import Product
from app.models.stock import Stock
from app.schemas.cart import (
    CartItemAdd,
    CartItemUpdate,
    CartItemResponse,
    CartResponse,
)
from app.core.exceptions import NotFoundException, BadRequestException


class CartService:
    @classmethod
    def get_cart(cls, db: Session, user_id: str) -> CartResponse:
        items = db.query(CartItem).filter(CartItem.user_id == user_id).order_by(CartItem.added_at.desc()).all()
        response_items: List[CartItemResponse] = []
        total_items = 0
        total_amount = 0.0

        for item in items:
            v = item.variant
            if not v:
                continue

            price = float(v.product.price) if (v.product and v.product.price is not None) else 0.0
            subtotal = round(price * item.quantity, 2)
            total_items += item.quantity
            total_amount += subtotal

            # Total stock across all branches for this variant
            stocks = db.query(Stock).filter(Stock.variant_id == v.id).all()
            available_stock = sum(s.quantity for s in stocks)

            resp_item = CartItemResponse(
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
                subtotal=subtotal,
                image_url=v.product.image_url if v.product else None,
                available_stock=available_stock,
            )
            response_items.append(resp_item)

        return CartResponse(
            items=response_items,
            total_items=total_items,
            total_amount=round(total_amount, 2),
        )

    @classmethod
    def add_item(cls, db: Session, user_id: str, data: CartItemAdd) -> CartResponse:
        variant = db.query(ProductVariant).filter(ProductVariant.id == data.variant_id).first()
        if not variant:
            raise NotFoundException(detail="Variante de producto no encontrada")

        if variant.product and not variant.product.is_active:
            raise BadRequestException(detail="El producto se encuentra inactivo")

        existing_item = (
            db.query(CartItem)
            .filter(CartItem.user_id == user_id, CartItem.variant_id == data.variant_id)
            .first()
        )

        if existing_item:
            existing_item.quantity += data.quantity
        else:
            new_item = CartItem(
                user_id=user_id,
                variant_id=data.variant_id,
                quantity=data.quantity,
            )
            db.add(new_item)

        db.commit()
        return cls.get_cart(db, user_id)

    @classmethod
    def update_item_quantity(
        cls, db: Session, user_id: str, item_id: str, data: CartItemUpdate
    ) -> CartResponse:
        item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.user_id == user_id).first()
        if not item:
            raise NotFoundException(detail="Item del carrito no encontrado")

        item.quantity = data.quantity
        db.commit()
        return cls.get_cart(db, user_id)

    @classmethod
    def remove_item(cls, db: Session, user_id: str, item_id: str) -> CartResponse:
        item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.user_id == user_id).first()
        if not item:
            raise NotFoundException(detail="Item del carrito no encontrado")

        db.delete(item)
        db.commit()
        return cls.get_cart(db, user_id)

    @classmethod
    def clear_cart(cls, db: Session, user_id: str) -> CartResponse:
        db.query(CartItem).filter(CartItem.user_id == user_id).delete()
        db.commit()
        return CartResponse(items=[], total_items=0, total_amount=0.0)
