from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.cart import (
    CartItemAdd,
    CartItemUpdate,
    CartResponse,
)
from app.services.cart_service import CartService

router = APIRouter(prefix="/cart", tags=["Shopping Cart (CU12)"])


@router.get(
    "",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener el carrito de compras del usuario actual",
)
def get_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CartService.get_cart(db=db, user_id=current_user.id)


@router.post(
    "/items",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Agregar una variante de producto al carrito",
)
def add_to_cart(
    payload: CartItemAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CartService.add_item(db=db, user_id=current_user.id, data=payload)


@router.put(
    "/items/{item_id}",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Modificar la cantidad de un item en el carrito",
)
def update_cart_item(
    item_id: str,
    payload: CartItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CartService.update_item_quantity(
        db=db, user_id=current_user.id, item_id=item_id, data=payload
    )


@router.delete(
    "/items/{item_id}",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Eliminar un item del carrito de compras",
)
def remove_from_cart(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CartService.remove_item(db=db, user_id=current_user.id, item_id=item_id)


@router.delete(
    "",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Vaciar completamente el carrito de compras",
)
def clear_cart(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CartService.clear_cart(db=db, user_id=current_user.id)
