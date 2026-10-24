from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.modelos.sucursal import Sucursal
from app.modelos.usuario import Usuario
from app.esquemas.sucursal import (
    SucursalCreate,
    SucursalUpdate,
    SucursalResponse,
    AsignarPersonalRequest,
)
from app.servicios.sucursal_service import SucursalService
from app.api.dependencias import get_current_user, require_admin
from app.nucleo.excepciones import NoEncontradoException
from app.nucleo.ambito_sucursal import resolve_branch

router = APIRouter(prefix="/branches", tags=["Branches"])


@router.get(
    "",
    response_model=List[SucursalResponse],
    status_code=status.HTTP_200_OK,
    summary="List all branches",
    description="Returns all registered branches, optionally filtered by city and active status.",
)
def list_branches(
    city: Optional[str] = Query(None, description="Filter by city name"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    branches = SucursalService.list_branches(db, city=city, is_active=is_active)
    if current_user.role in ("STORE_MANAGER", "CASHIER"):
        scope = resolve_branch(current_user)
        branches = [branch for branch in branches if branch.id == scope]
    return [SucursalService.format_response(b) for b in branches]


@router.post(
    "",
    response_model=SucursalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new branch (Admin only)",
    description="Registers a new store or warehouse. Validates duplicate names in the same city (FA03).",
)
def create_branch(
    request: SucursalCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    branch = SucursalService.create_branch(db, request)
    return SucursalService.format_response(branch)


@router.get(
    "/{branch_id}",
    response_model=SucursalResponse,
    status_code=status.HTTP_200_OK,
    summary="Get branch by ID",
)
def get_branch(
    branch_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if current_user.role in ("STORE_MANAGER", "CASHIER"):
        resolve_branch(current_user, branch_id)
    branch = SucursalService.get_by_id(db, branch_id)
    if not branch:
        raise NoEncontradoException(detail="Sucursal no encontrada")
    return SucursalService.format_response(branch)


@router.put(
    "/{branch_id}",
    response_model=SucursalResponse,
    status_code=status.HTTP_200_OK,
    summary="Update branch details (Admin only)",
)
def update_branch(
    branch_id: str,
    request: SucursalUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    branch = SucursalService.get_by_id(db, branch_id)
    if not branch:
        raise NoEncontradoException(detail="Sucursal no encontrada")
    updated = SucursalService.update_branch(db, branch, request)
    return SucursalService.format_response(updated)


@router.patch(
    "/{branch_id}/toggle-status",
    response_model=SucursalResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle active status of a branch (Admin only)",
    description="Marks a branch as active or temporarily closed (FA02).",
)
def toggle_branch_status(
    branch_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    branch = SucursalService.get_by_id(db, branch_id)
    if not branch:
        raise NoEncontradoException(detail="Sucursal no encontrada")
    updated = SucursalService.toggle_status(db, branch)
    return SucursalService.format_response(updated)


@router.post(
    "/{branch_id}/staff",
    response_model=SucursalResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign or transfer staff to branch (Admin only)",
    description="Assigns or transfers employees (Store Managers or Cashiers) to this branch (FA01).",
)
def assign_staff(
    branch_id: str,
    request: AsignarPersonalRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    branch = SucursalService.get_by_id(db, branch_id)
    if not branch:
        raise NoEncontradoException(detail="Sucursal no encontrada")
    updated = SucursalService.assign_staff(db, branch, request.user_ids)
    return SucursalService.format_response(updated)


@router.delete(
    "/{branch_id}/staff/{user_id}",
    response_model=SucursalResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove staff member from branch (Admin only)",
)
def remove_staff(
    branch_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin),
):
    branch = SucursalService.get_by_id(db, branch_id)
    if not branch:
        raise NoEncontradoException(detail="Sucursal no encontrada")
    updated = SucursalService.remove_staff(db, branch, user_id)
    return SucursalService.format_response(updated)
