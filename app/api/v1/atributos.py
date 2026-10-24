from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.modelos.usuario import Usuario
from app.esquemas.atributo_catalogo import (
    CategoriaCreate,
    CategoriaUpdate,
    CategoriaResponse,
    TallaCreate,
    TallaUpdate,
    TallaResponse,
    ColorCreate,
    ColorUpdate,
    ColorResponse,
)
from app.servicios.atributo_catalogo_service import AtributoCatalogoService
from app.api.dependencias import get_current_user, require_admin, require_roles
from app.modelos.usuario import RolUsuario

router = APIRouter(prefix="/attributes", tags=["Catalog Attributes"])


# ----------------------------------------------------
# CATEGORIES ENDPOINTS (CU05)
# ----------------------------------------------------
@router.get(
    "/categories",
    response_model=List[CategoriaResponse],
    status_code=status.HTTP_200_OK,
    summary="List clothing categories",
)
def list_categories(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by category name"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return AtributoCatalogoService.list_categories(db, is_active=is_active, search=search)


@router.post(
    "/categories",
    response_model=CategoriaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create category (Admin only)",
)
def create_category(
    request: CategoriaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return AtributoCatalogoService.create_category(db, request)


@router.put(
    "/categories/{category_id}",
    response_model=CategoriaResponse,
    status_code=status.HTTP_200_OK,
    summary="Update category (Admin only)",
)
def update_category(
    category_id: str,
    request: CategoriaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return AtributoCatalogoService.update_category(db, category_id, request)


@router.patch(
    "/categories/{category_id}/toggle-status",
    response_model=CategoriaResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle category active status (Admin only)",
)
def toggle_category_status(
    category_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return AtributoCatalogoService.toggle_category_status(db, category_id)


# ----------------------------------------------------
# SIZES ENDPOINTS (CU05)
# ----------------------------------------------------
@router.get(
    "/sizes",
    response_model=List[TallaResponse],
    status_code=status.HTTP_200_OK,
    summary="List clothing sizes",
)
def list_sizes(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    category_type: Optional[str] = Query(None, description="Filter by category type"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return AtributoCatalogoService.list_sizes(db, is_active=is_active, category_type=category_type)


@router.post(
    "/sizes",
    response_model=TallaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create size (Admin only)",
)
def create_size(
    request: TallaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return AtributoCatalogoService.create_size(db, request)


@router.put(
    "/sizes/{size_id}",
    response_model=TallaResponse,
    status_code=status.HTTP_200_OK,
    summary="Update size (Admin only)",
)
def update_size(
    size_id: str,
    request: TallaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return AtributoCatalogoService.update_size(db, size_id, request)


@router.patch(
    "/sizes/{size_id}/toggle-status",
    response_model=TallaResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle size active status (Admin only)",
)
def toggle_size_status(
    size_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return AtributoCatalogoService.toggle_size_status(db, size_id)


# ----------------------------------------------------
# COLORS ENDPOINTS (CU05)
# ----------------------------------------------------
@router.get(
    "/colors",
    response_model=List[ColorResponse],
    status_code=status.HTTP_200_OK,
    summary="List clothing colors",
)
def list_colors(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by color name"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    return AtributoCatalogoService.list_colors(db, is_active=is_active, search=search)


@router.post(
    "/colors",
    response_model=ColorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create color (Admin only)",
)
def create_color(
    request: ColorCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return AtributoCatalogoService.create_color(db, request)


@router.put(
    "/colors/{color_id}",
    response_model=ColorResponse,
    status_code=status.HTTP_200_OK,
    summary="Update color (Admin only)",
)
def update_color(
    color_id: str,
    request: ColorUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return AtributoCatalogoService.update_color(db, color_id, request)


@router.patch(
    "/colors/{color_id}/toggle-status",
    response_model=ColorResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle color active status (Admin only)",
)
def toggle_color_status(
    color_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)),
):
    return AtributoCatalogoService.toggle_color_status(db, color_id)
