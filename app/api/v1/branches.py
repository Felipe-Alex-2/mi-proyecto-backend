from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.branch import Branch
from app.models.user import User
from app.schemas.branch import (
    BranchCreate,
    BranchUpdate,
    BranchResponse,
    AssignStaffRequest,
)
from app.services.branch_service import BranchService
from app.api.deps import get_current_user, require_admin
from app.core.exceptions import NotFoundException

router = APIRouter(prefix="/branches", tags=["Branches"])


@router.get(
    "",
    response_model=List[BranchResponse],
    status_code=status.HTTP_200_OK,
    summary="List all branches",
    description="Returns all registered branches, optionally filtered by city and active status.",
)
def list_branches(
    city: Optional[str] = Query(None, description="Filter by city name"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    branches = BranchService.list_branches(db, city=city, is_active=is_active)
    return [BranchService.format_response(b) for b in branches]


@router.post(
    "",
    response_model=BranchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new branch (Admin only)",
    description="Registers a new store or warehouse. Validates duplicate names in the same city (FA03).",
)
def create_branch(
    request: BranchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    branch = BranchService.create_branch(db, request)
    return BranchService.format_response(branch)


@router.get(
    "/{branch_id}",
    response_model=BranchResponse,
    status_code=status.HTTP_200_OK,
    summary="Get branch by ID",
)
def get_branch(
    branch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    branch = BranchService.get_by_id(db, branch_id)
    if not branch:
        raise NotFoundException(detail="Sucursal no encontrada")
    return BranchService.format_response(branch)


@router.put(
    "/{branch_id}",
    response_model=BranchResponse,
    status_code=status.HTTP_200_OK,
    summary="Update branch details (Admin only)",
)
def update_branch(
    branch_id: str,
    request: BranchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    branch = BranchService.get_by_id(db, branch_id)
    if not branch:
        raise NotFoundException(detail="Sucursal no encontrada")
    updated = BranchService.update_branch(db, branch, request)
    return BranchService.format_response(updated)


@router.patch(
    "/{branch_id}/toggle-status",
    response_model=BranchResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle active status of a branch (Admin only)",
    description="Marks a branch as active or temporarily closed (FA02).",
)
def toggle_branch_status(
    branch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    branch = BranchService.get_by_id(db, branch_id)
    if not branch:
        raise NotFoundException(detail="Sucursal no encontrada")
    updated = BranchService.toggle_status(db, branch)
    return BranchService.format_response(updated)


@router.post(
    "/{branch_id}/staff",
    response_model=BranchResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign or transfer staff to branch (Admin only)",
    description="Assigns or transfers employees (Store Managers or Cashiers) to this branch (FA01).",
)
def assign_staff(
    branch_id: str,
    request: AssignStaffRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    branch = BranchService.get_by_id(db, branch_id)
    if not branch:
        raise NotFoundException(detail="Sucursal no encontrada")
    updated = BranchService.assign_staff(db, branch, request.user_ids)
    return BranchService.format_response(updated)


@router.delete(
    "/{branch_id}/staff/{user_id}",
    response_model=BranchResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove staff member from branch (Admin only)",
)
def remove_staff(
    branch_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    branch = BranchService.get_by_id(db, branch_id)
    if not branch:
        raise NotFoundException(detail="Sucursal no encontrada")
    updated = BranchService.remove_staff(db, branch, user_id)
    return BranchService.format_response(updated)
