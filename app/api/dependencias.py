from typing import Generator, Optional
from fastapi import Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.modelos.usuario import Usuario
from app.servicios.usuario_service import UsuarioService
from app.servicios.autenticacion_service import AutenticacionService
from app.nucleo.seguridad import decode_token
from app.nucleo.excepciones import AutenticacionException, AccesoDenegadoException
from app.modelos.usuario import Usuario, RolUsuario

security_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    """Dependency to retrieve authenticated user from Bearer JWT."""
    if not credentials:
        raise AutenticacionException(detail="Authentication credentials were not provided")

    token = credentials.credentials

    # Verify if token is blacklisted
    if AutenticacionService.is_token_blacklisted(db, token):
        raise AutenticacionException(detail="Token has been revoked")

    payload = decode_token(token)
    if not payload:
        raise AutenticacionException(detail="Invalid or expired token")

    if payload.get("type") != "access":
        raise AutenticacionException(detail="Invalid token type")

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise AutenticacionException(detail="Could not validate credentials")

    user = db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.id == user_id).first()
    if not user:
        raise AutenticacionException(detail="Usuario not found")

    if not user.is_active:
        raise AutenticacionException(detail="Usuario account is inactive")

    from app.nucleo.ambito_empresa import configure_context
    configure_context(db, user, request)
    return user


def get_current_user_flexible(
    request: Request,
    token: Optional[str] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    """Retrieves user from either Authorization: Bearer header or ?token= query parameter."""
    raw_token = credentials.credentials if credentials else token
    if not raw_token:
        raise AutenticacionException(detail="Authentication credentials were not provided")

    if AutenticacionService.is_token_blacklisted(db, raw_token):
        raise AutenticacionException(detail="Token has been revoked")

    payload = decode_token(raw_token)
    if not payload:
        raise AutenticacionException(detail="Invalid or expired token")

    if payload.get("type") != "access":
        raise AutenticacionException(detail="Invalid token type")

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise AutenticacionException(detail="Could not validate credentials")

    user = db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.id == user_id).first()
    if not user:
        raise AutenticacionException(detail="Usuario not found")

    if not user.is_active:
        raise AutenticacionException(detail="Usuario account is inactive")

    from app.nucleo.ambito_empresa import configure_context
    configure_context(db, user, request)
    return user



def require_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """Dependency to ensure the current user has the ADMIN role."""
    user_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if user_role != RolUsuario.ADMIN.value:
        raise AccesoDenegadoException(detail="Se requieren permisos de Administrador General")
    return current_user


def require_roles(*allowed_roles: RolUsuario):
    """Dependency generator to restrict endpoints to specific roles."""
    roles_str = [r.value if hasattr(r, "value") else str(r) for r in allowed_roles]

    def role_checker(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        user_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        if user_role not in roles_str:
            raise AccesoDenegadoException(detail="No tienes los permisos necesarios para realizar esta acción")
        return current_user

    return role_checker
