from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.api.dependencias import get_current_user
from app.base_datos import get_db
from app.modelos.usuario import Usuario
from app.esquemas.carrito import (
    CarritoItemAdd,
    CarritoItemUpdate,
    CarritoResponse,
)
from app.servicios.carrito_service import CarritoService

router = APIRouter(prefix="/cart", tags=["Shopping Cart (CU12)"])


@router.get(
    "",
    response_model=CarritoResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener el carrito de compras del usuario actual",
)
def get_cart(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return CarritoService.get_cart(db=db, user_id=current_user.id)


@router.post(
    "/items",
    response_model=CarritoResponse,
    status_code=status.HTTP_200_OK,
    summary="Agregar una variante de producto al carrito",
)
def add_to_cart(
    payload: CarritoItemAdd,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return CarritoService.add_item(db=db, user_id=current_user.id, data=payload)


@router.put(
    "/items/{item_id}",
    response_model=CarritoResponse,
    status_code=status.HTTP_200_OK,
    summary="Modificar la cantidad de un item en el carrito",
)
def update_cart_item(
    item_id: str,
    payload: CarritoItemUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return CarritoService.update_item_quantity(
        db=db, user_id=current_user.id, item_id=item_id, data=payload
    )


@router.delete(
    "/items/{item_id}",
    response_model=CarritoResponse,
    status_code=status.HTTP_200_OK,
    summary="Eliminar un item del carrito de compras",
)
def remove_from_cart(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return CarritoService.remove_item(db=db, user_id=current_user.id, item_id=item_id)


@router.delete(
    "",
    response_model=CarritoResponse,
    status_code=status.HTTP_200_OK,
    summary="Vaciar completamente el carrito de compras",
)
def clear_cart(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return CarritoService.clear_cart(db=db, user_id=current_user.id)
