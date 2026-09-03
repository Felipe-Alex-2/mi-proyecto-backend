from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.token_blacklist import TokenBlacklist
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RefreshTokenRequest
from app.schemas.user import UserResponse
from app.services.user_service import UserService
from app.core.security import (
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.core.exceptions import AuthException, ConflictException, BadRequestException
from app.config import settings


class AuthService:
    @staticmethod
    def register(db: Session, request: RegisterRequest) -> User:
        """Register a new user account."""
        existing = UserService.get_by_email(db, request.email)
        if existing:
            raise ConflictException(detail="Email is already registered")

        user = UserService.create(
            db,
            obj_in=request,  # matches email, password, full_name
        )
        return user

    @staticmethod
    def authenticate(db: Session, request: LoginRequest) -> User:
        """Verify user credentials."""
        user = UserService.get_by_email(db, request.email)
        if not user:
            raise AuthException(detail="Invalid email or password")

        if not verify_password(request.password, user.hashed_password):
            raise AuthException(detail="Invalid email or password")

        if not user.is_active:
            raise AuthException(detail="Inactive user account")

        return user

    @classmethod
    def create_tokens_for_user(cls, user: User) -> TokenResponse:
        """Generate access and refresh tokens for user."""
        access_token = create_access_token(subject=user.id)
        refresh_token = create_refresh_token(subject=user.id)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserResponse.model_validate(user),
        )

    @classmethod
    def refresh_access_token(cls, db: Session, request: RefreshTokenRequest) -> TokenResponse:
        """Generate a new access token using a valid refresh token."""
        # Check if token is blacklisted
        if cls.is_token_blacklisted(db, request.refresh_token):
            raise AuthException(detail="Refresh token has been revoked")

        payload = decode_token(request.refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise AuthException(detail="Invalid or expired refresh token")

        user_id = payload.get("sub")
        if not user_id:
            raise AuthException(detail="Invalid token payload")

        user = UserService.get_by_id(db, user_id)
        if not user or not user.is_active:
            raise AuthException(detail="User not found or inactive")

        # Create new tokens
        return cls.create_tokens_for_user(user)

    @staticmethod
    def blacklist_token(db: Session, token: str) -> None:
        """Add a token to the revocation blacklist."""
        payload = decode_token(token)
        expires_at = None
        if payload and "exp" in payload:
            expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        # Check if already in blacklist
        existing = db.query(TokenBlacklist).filter(TokenBlacklist.token == token).first()
        if not existing:
            blacklisted = TokenBlacklist(token=token, expires_at=expires_at)
            db.add(blacklisted)
            db.commit()

    @staticmethod
    def is_token_blacklisted(db: Session, token: str) -> bool:
        """Check if a token exists in the blacklist."""
        return db.query(TokenBlacklist).filter(TokenBlacklist.token == token).first() is not None
