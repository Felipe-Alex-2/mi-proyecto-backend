from typing import Generator, Optional
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.services.user_service import UserService
from app.services.auth_service import AuthService
from app.core.security import decode_token
from app.core.exceptions import AuthException

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
