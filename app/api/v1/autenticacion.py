from fastapi import APIRouter, Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.modelos.usuario import Usuario
from app.esquemas.autenticacion import (
    RegistroRequest,
    InicioSesionRequest,
    TokenResponse,
    RenovarTokenRequest,
    RecuperarContrasenaRequest,
    RestablecerContrasenaRequest,
)
from app.esquemas.usuario import UsuarioResponse
from app.esquemas.comun import MensajeResponse
from app.servicios.autenticacion_service import AutenticacionService
from app.api.dependencias import get_current_user, security_bearer
from app.esquemas.bitacora import BitacoraCreate
from app.servicios.bitacora_service import BitacoraService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UsuarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Creates a new user account with unique email address and secure password.",
)
def register(request: RegistroRequest, http_request: Request, db: Session = Depends(get_db)):
    user = AutenticacionService.register(db, request)
    BitacoraService.log_event(
        db=db,
        user=user,
        action="REGISTRO_USUARIO",
        description=f"Nuevo usuario registrado: {user.email}",
        category="SEGURIDAD",
        ip_address=http_request.client.host if http_request.client else None,
    )
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and get JWT tokens",
    description="Validates email and password, returning access and refresh JWT tokens.",
)
def login(request: InicioSesionRequest, http_request: Request, db: Session = Depends(get_db)):
    user = AutenticacionService.authenticate(db, request)
    BitacoraService.create(
        db=db,
        user=user,
        payload=BitacoraCreate(
            action="LOGIN",
            description="Inicio de sesión exitoso",
            category="SEGURIDAD",
        ),
        request=http_request,
    )
    return AutenticacionService.create_tokens_for_user(user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
    description="Takes a valid refresh token and issues a new access token.",
)
def refresh(request: RenovarTokenRequest, db: Session = Depends(get_db)):
    return AutenticacionService.refresh_access_token(db, request)


@router.post(
    "/logout",
    response_model=MensajeResponse,
    status_code=status.HTTP_200_OK,
    summary="Logout user and revoke access token",
    description="Adds the provided Bearer token to the blacklist so it cannot be used again.",
)
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    AutenticacionService.blacklist_token(db, credentials.credentials)
    BitacoraService.create(
        db=db,
        user=current_user,
        payload=BitacoraCreate(
            action="LOGOUT",
            description="Cierre de sesión",
            category="SEGURIDAD",
        ),
    )
    return MensajeResponse(message="Successfully logged out")


@router.post(
    "/forgot-password",
    response_model=MensajeResponse,
    status_code=status.HTTP_200_OK,
    summary="Request password reset",
    description="Sends a 6-digit one-time reset token to the user's email. Always returns success to prevent email enumeration.",
)
def forgot_password(request: RecuperarContrasenaRequest, db: Session = Depends(get_db)):
    AutenticacionService.request_password_reset(db, request.email)
    return MensajeResponse(
        message="Si el correo está registrado, recibirás un código de recuperación en tu bandeja de entrada."
    )


@router.post(
    "/reset-password",
    response_model=MensajeResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset password with token",
    description="Validates the 6-digit reset token and updates the user's password. Token is single-use and expires in 7 minutes.",
)
def reset_password(request: RestablecerContrasenaRequest, db: Session = Depends(get_db)):
    AutenticacionService.reset_password(db, request.email, request.token, request.new_password)
    return MensajeResponse(message="Contraseña actualizada exitosamente. Ya puedes iniciar sesión.")

