from typing import Generator, Optional
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.services.user_service import UserService
from app.services.auth_service import AuthService
from app.core.security import decode_token
from app.core.exceptions import AuthException, ForbiddenException
from app.models.user import User, UserRole

security_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Dependency to retrieve authenticated user from Bearer JWT."""
    if not credentials:
        raise AuthException(detail="Authentication credentials were not provided")

    token = credentials.credentials

    # Verify if token is blacklisted
    if AuthService.is_token_blacklisted(db, token):
        raise AuthException(detail="Token has been revoked")

    payload = decode_token(token)
    if not payload:
        raise AuthException(detail="Invalid or expired token")

    if payload.get("type") != "access":
        raise AuthException(detail="Invalid token type")

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise AuthException(detail="Could not validate credentials")

    user = UserService.get_by_id(db, user_id)
    if not user:
        raise AuthException(detail="User not found")

    if not user.is_active:
        raise AuthException(detail="User account is inactive")

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency to ensure the current user has the ADMIN role."""
    user_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if user_role != UserRole.ADMIN.value:
        raise ForbiddenException(detail="Se requieren permisos de Administrador General")
    return current_user


def require_roles(*allowed_roles: UserRole):
    """Dependency generator to restrict endpoints to specific roles."""
    roles_str = [r.value if hasattr(r, "value") else str(r) for r in allowed_roles]

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        if user_role not in roles_str:
            raise ForbiddenException(detail="No tienes los permisos necesarios para realizar esta acción")
        return current_user

    return role_checker
