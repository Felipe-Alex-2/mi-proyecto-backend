from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.schemas.user import UserResponse
from app.schemas.common import MessageResponse
from app.services.auth_service import AuthService
from app.api.deps import get_current_user, security_bearer

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Creates a new user account with unique email address and secure password.",
)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    user = AuthService.register(db, request)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and get JWT tokens",
    description="Validates email and password, returning access and refresh JWT tokens.",
)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = AuthService.authenticate(db, request)
    return AuthService.create_tokens_for_user(user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
    description="Takes a valid refresh token and issues a new access token.",
)
def refresh(request: RefreshTokenRequest, db: Session = Depends(get_db)):
    return AuthService.refresh_access_token(db, request)


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Logout user and revoke access token",
    description="Adds the provided Bearer token to the blacklist so it cannot be used again.",
)
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    AuthService.blacklist_token(db, credentials.credentials)
    return MessageResponse(message="Successfully logged out")


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Request password reset",
    description="Sends a 6-digit one-time reset token to the user's email. Always returns success to prevent email enumeration.",
)
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    AuthService.request_password_reset(db, request.email)
    return MessageResponse(
        message="Si el correo está registrado, recibirás un código de recuperación en tu bandeja de entrada."
    )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset password with token",
    description="Validates the 6-digit reset token and updates the user's password. Token is single-use and expires in 7 minutes.",
)
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    AuthService.reset_password(db, request.email, request.token, request.new_password)
    return MessageResponse(message="Contraseña actualizada exitosamente. Ya puedes iniciar sesión.")

