from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdate, UserCreateAdmin, UserUpdateAdmin
from app.services.user_service import UserService
from app.api.deps import get_current_user, require_admin
from app.core.exceptions import ConflictException, NotFoundException

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
    description="Returns the profile information of the currently authenticated user.",
)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update current user profile",
    description="Updates the profile details (name, email, or password) of the authenticated user.",
)
def update_me(
    request: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if request.email and request.email.lower().strip() != current_user.email:
        existing = UserService.get_by_email(db, request.email)
        if existing:
            raise ConflictException(detail="Email is already taken by another account")

    updated_user = UserService.update(db, current_user, request)
    return updated_user


@router.get(
    "",
    response_model=List[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="List all users with filters (Admin only)",
    description="Returns a list of users. Accessible only by Administrators.",
)
def list_users(
    search: Optional[str] = Query(None, description="Search by name, email or phone"),
    role: Optional[str] = Query(None, description="Filter by role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return UserService.list_users(
        db, search=search, role=role, is_active=is_active, skip=skip, limit=limit
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user/employee (Admin only)",
    description="Allows an Administrator to create an employee account with a specific role.",
)
def create_user(
    request: UserCreateAdmin,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return UserService.create_by_admin(db, request)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get user details by ID (Admin only)",
)
def get_user(
    user_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = UserService.get_by_id(db, user_id)
    if not user:
        raise NotFoundException(detail="Usuario no encontrado")
    return user


@router.put(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user/employee data and role (Admin only)",
)
def update_user(
    user_id: str,
    request: UserUpdateAdmin,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = UserService.get_by_id(db, user_id)
    if not user:
        raise NotFoundException(detail="Usuario no encontrado")
    return UserService.update_by_admin(db, user, request)


@router.patch(
    "/{user_id}/toggle-status",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate or deactivate a user account (Admin only)",
)
def toggle_user_status(
    user_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = UserService.get_by_id(db, user_id)
    if not user:
        raise NotFoundException(detail="Usuario no encontrado")
    return UserService.toggle_status(db, user, current_user.id)
