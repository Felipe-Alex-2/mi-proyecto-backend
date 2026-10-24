from app.esquemas.comun import MensajeResponse
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.api.dependencias import get_current_user, require_roles
from app.base_datos import get_db
from app.modelos.usuario import Usuario, RolUsuario
from app.esquemas.movimiento_inventario import (
    MovimientoInventarioCreate,
    MovimientoInventarioResponse,
    MovimientoInventarioUpdate,
    ResumenInventarioSucursal,
)
from app.servicios.movimiento_inventario_service import MovimientoInventarioService
from app.nucleo.ambito_sucursal import resolve_branch

router = APIRouter(prefix="/inventory", tags=["Inventory Movements (CU09)"])


@router.post(
    "/movements",
    response_model=MovimientoInventarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un movimiento de inventario (Entrada, Salida, Ajuste, Devolución)",
)
def create_movement(
    payload: MovimientoInventarioCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return MovimientoInventarioService.create_movement(db=db, user=current_user, data=payload)


@router.get(
    "/movements",
    response_model=List[MovimientoInventarioResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar historial de movimientos de inventario con filtros",
)
def list_movements(
    branch_id: Optional[str] = Query(None, description="Filtrar por sucursal"),
    type: Optional[str] = Query(None, description="Filtrar por tipo (ENTRY, EXIT, ADJUSTMENT, RETURN)"),
    variant_id: Optional[str] = Query(None, description="Filtrar por ID de variante"),
    product_id: Optional[str] = Query(None, description="Filtrar por ID de producto"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return MovimientoInventarioService.list_movements(
        db=db,
        user=current_user,
        branch_id=branch_id,
        movement_type=type,
        variant_id=variant_id,
        product_id=product_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/movements/{id}",
    response_model=MovimientoInventarioResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener detalle de un movimiento de inventario específico",
)
def get_movement(
    id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return MovimientoInventarioService.get_movement(db=db, movement_id=id, user=current_user)


@router.get(
    "/summary/{branch_id}",
    response_model=ResumenInventarioSucursal,
    status_code=status.HTTP_200_OK,
    summary="Resumen de inventario y alertas de stock de una sucursal",
)
def get_branch_summary(
    branch_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER, RolUsuario.CASHIER)),
):
    resolve_branch(current_user, branch_id)
    return MovimientoInventarioService.get_branch_summary(db=db, branch_id=branch_id)


@router.put(
    "/movements/{id}",
    response_model=MovimientoInventarioResponse,
    status_code=status.HTTP_200_OK,
    summary="Editar motivo o referencia de un movimiento de inventario",
)
def update_movement(
    id: str,
    payload: MovimientoInventarioUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return MovimientoInventarioService.update_movement(db=db, movement_id=id, user=current_user, data=payload)


@router.delete(
    "/movements/{id}",
    response_model=MensajeResponse,
    status_code=status.HTTP_200_OK,
    summary="Eliminar y revertir el impacto de stock de un movimiento de inventario",
)
def delete_movement(
    id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    MovimientoInventarioService.delete_movement(db=db, movement_id=id, user=current_user)
    return MensajeResponse(message="Movimiento de inventario eliminado y stock revertido exitosamente")
