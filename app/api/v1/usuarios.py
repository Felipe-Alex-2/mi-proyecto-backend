from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.modelos.usuario import Usuario
from app.esquemas.usuario import UsuarioResponse, UsuarioUpdate, UsuarioCreateAdmin, UsuarioUpdateAdmin
from app.servicios.bitacora_service import BitacoraService
from app.servicios.usuario_service import UsuarioService
from app.api.dependencias import get_current_user, require_admin
from app.nucleo.excepciones import ConflictoException, NoEncontradoException, AccesoDenegadoException, SolicitudInvalidaException

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UsuarioResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
    description="Returns the profile information of the currently authenticated user.",
)
def get_me(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    return UsuarioResponse.for_context(db, current_user)


@router.put(
    "/me",
    response_model=UsuarioResponse,
    status_code=status.HTTP_200_OK,
    summary="Update current user profile",
    description="Updates the profile details (name, email, or password) of the authenticated user.",
)
def update_me(
    request: UsuarioUpdate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if request.email and request.email.lower().strip() != current_user.email:
        existing = UsuarioService.get_by_email(db, request.email)
        if existing:
            raise ConflictoException(detail="Email is already taken by another account")

    updated_user = UsuarioService.update(db, current_user, request)
    BitacoraService.log_event(
        db=db,
        user=current_user,
        action="ACTUALIZAR_PERFIL",
        description=f"Usuario actualizó su propio perfil: {updated_user.email}",
        category="SEGURIDAD",
    )
    return UsuarioResponse.for_context(db, updated_user)


@router.get(
    "",
    response_model=List[UsuarioResponse],
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
    current_user: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return UsuarioService.list_users(
        db, search=search, role=role, is_active=is_active, skip=skip, limit=limit
    )


@router.post(
    "",
    response_model=UsuarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user/employee (Admin only)",
    description="Allows an Administrator to create an employee account with a specific role.",
)
def create_user(
    request: UsuarioCreateAdmin,
    current_user: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    created = UsuarioService.create_by_admin(db, request)
    BitacoraService.log_event(
        db=db,
        user=current_user,
        action="CREAR_USUARIO",
        description=f"Administrador creó cuenta para {created.email} con rol {created.role if created.role else 'USUARIO'}",
        category="ADMINISTRACION",
    )
    return created


@router.get(
    "/{user_id}",
    response_model=UsuarioResponse,
    status_code=status.HTTP_200_OK,
    summary="Get user details by ID (Admin only)",
)
def get_user(
    user_id: str,
    current_user: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = UsuarioService.get_by_id(db, user_id)
    if not user or (db.info.get("tenant_context") and user.tenant_id != db.info.get("tenant_id")):
        raise NoEncontradoException(detail="Usuario no encontrado")
    return user


@router.put(
    "/{user_id}",
    response_model=UsuarioResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user/employee data and role (Admin only)",
)
def update_user(
    user_id: str,
    request: UsuarioUpdateAdmin,
    current_user: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = UsuarioService.get_by_id(db, user_id)
    if not user or (db.info.get("tenant_context") and user.tenant_id != db.info.get("tenant_id")):
        raise NoEncontradoException(detail="Usuario no encontrado")
    if user.is_saas_admin:
        if not current_user.is_saas_admin:
            raise AccesoDenegadoException(detail='Solo un administrador SaaS puede modificar una cuenta de plataforma')
        if (request.role is not None and request.role.value != 'ADMIN') or request.is_active is False:
            raise SolicitudInvalidaException(detail='La cuenta de plataforma debe conservar su rol de administrador y permanecer activa')
    updated = UsuarioService.update_by_admin(db, user, request)
    BitacoraService.log_event(
        db=db,
        user=current_user,
        action="ACTUALIZAR_USUARIO",
        description=f"Administrador actualizó cuenta de {updated.email}",
        category="ADMINISTRACION",
    )
    return updated


@router.patch(
    "/{user_id}/toggle-status",
    response_model=UsuarioResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate or deactivate a user account (Admin only)",
)
def toggle_user_status(
    user_id: str,
    current_user: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = UsuarioService.get_by_id(db, user_id)
    if not user or (db.info.get("tenant_context") and user.tenant_id != db.info.get("tenant_id")):
        raise NoEncontradoException(detail="Usuario no encontrado")
    if user.is_saas_admin:
        raise AccesoDenegadoException(detail='La cuenta de administración SaaS no puede desactivarse desde Personal')
    toggled = UsuarioService.toggle_status(db, user, current_user.id)
    status_str = "activo" if toggled.is_active else "desactivado"
    BitacoraService.log_event(
        db=db,
        user=current_user,
        action="CAMBIAR_ESTADO_USUARIO",
        description=f"Administrador cambió estado de {toggled.email} a {status_str}",
        category="ADMINISTRACION",
    )
    return toggled
