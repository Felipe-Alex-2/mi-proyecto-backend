from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import secrets
from sqlalchemy.orm import Session
from app.modelos.usuario import Usuario
from app.modelos.tokens_revocados import ListaTokensRevocados
from app.modelos.token_restabler_contrasena import TokenRestablecimientoContrasena
from app.esquemas.autenticacion import RegistroRequest, InicioSesionRequest, TokenResponse, RenovarTokenRequest
from app.esquemas.usuario import UsuarioResponse
from app.servicios.usuario_service import UsuarioService
from app.servicios.correo_service import CorreoService
from app.nucleo.seguridad import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.nucleo.excepciones import AutenticacionException, ConflictoException, SolicitudInvalidaException
from app.configuracion import settings


class AutenticacionService:
    @staticmethod
    def register(db: Session, request: RegistroRequest) -> Usuario:
        """Register a new user account."""
        from app.modelos.saas import Empresa
        if db.query(Empresa.id).first() and (not request.tenant_id or not request.branch_id):
            raise SolicitudInvalidaException(detail='Escoge una empresa y una sucursal para crear tu cuenta.')
        existing = db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.email == request.email.lower().strip()).first()
        if existing:
            raise ConflictoException(detail="Email is already registered")

        if request.tenant_id or request.branch_id:
            from app.modelos.sucursal import Sucursal
            from app.modelos.saas import Empresa
            tenant = db.get(Empresa, request.tenant_id) if request.tenant_id else None
            branch = db.query(Sucursal).execution_options(skip_tenant=True).filter(Sucursal.id == request.branch_id, Sucursal.tenant_id == request.tenant_id, Sucursal.is_active == True).first()
            if not tenant or not tenant.is_active or not branch:
                raise SolicitudInvalidaException(detail="Selecciona una empresa y una sucursal válidas")
        user = UsuarioService.create(
            db,
            obj_in=request,  # matches email, password, full_name
        )
        if request.tenant_id or request.branch_id:
            from app.servicios.saas_service import SaasService
            SaasService.select_company(db, user, request.tenant_id, request.branch_id)
        return user

    @staticmethod
    def authenticate(db: Session, request: InicioSesionRequest) -> Usuario:
        """Verify user credentials."""
        user = db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.email == request.email.lower().strip()).first()
        if not user:
            raise AutenticacionException(detail="Invalid email or password")

        if not verify_password(request.password, user.hashed_password):
            raise AutenticacionException(detail="Invalid email or password")

        if not user.is_active:
            raise AutenticacionException(detail="Inactive user account")

        return user

    @classmethod
    def create_tokens_for_user(cls, user: Usuario) -> TokenResponse:
        """Generate access and refresh tokens for user."""
        access_token = create_access_token(
            subject=user.id,
            claims={"role": user.role, "email": user.email},
        )
        refresh_token = create_refresh_token(subject=user.id)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UsuarioResponse.model_validate(user),
        )

    @classmethod
    def refresh_access_token(cls, db: Session, request: RenovarTokenRequest) -> TokenResponse:
        """Generate a new access token using a valid refresh token."""
        # Check if token is blacklisted
        if cls.is_token_blacklisted(db, request.refresh_token):
            raise AutenticacionException(detail="Refresh token has been revoked")

        payload = decode_token(request.refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise AutenticacionException(detail="Invalid or expired refresh token")

        user_id = payload.get("sub")
        if not user_id:
            raise AutenticacionException(detail="Invalid token payload")

        user = db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.id == user_id).first()
        if not user or not user.is_active:
            raise AutenticacionException(detail="Usuario not found or inactive")

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
        existing = db.query(ListaTokensRevocados).filter(ListaTokensRevocados.token == token).first()
        if not existing:
            blacklisted = ListaTokensRevocados(token=token, expires_at=expires_at)
            db.add(blacklisted)
            db.commit()

    @staticmethod
    def is_token_blacklisted(db: Session, token: str) -> bool:
        """Check if a token exists in the blacklist."""
        return db.query(ListaTokensRevocados).filter(ListaTokensRevocados.token == token).first() is not None

    @staticmethod
    def _generate_numeric_token(length: int = 6) -> str:
        """Generate a cryptographically secure numeric token."""
        # Generate a random number with exactly `length` digits
        return "".join([str(secrets.randbelow(10)) for _ in range(length)])

    @classmethod
    def request_password_reset(cls, db: Session, email: str) -> bool:
        """Generate a 6-digit reset token, save it, and send via email.

        Always returns True to avoid revealing whether the email exists.
        """
        user = db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.email == email.lower().strip()).first()
        if not user:
            # Don't reveal whether the email exists
            return True

        # Invalidate any previous unused tokens for this user
        db.query(TokenRestablecimientoContrasena).filter(
            TokenRestablecimientoContrasena.user_id == user.id,
            TokenRestablecimientoContrasena.is_used == False,
        ).update({"is_used": True})
        db.commit()

        # Generate new token
        token = cls._generate_numeric_token(6)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.RESET_TOKEN_EXPIRE_MINUTES)

        reset_token = TokenRestablecimientoContrasena(
            user_id=user.id,
            token=token,
            expires_at=expires_at,
        )
        db.add(reset_token)
        db.commit()

        # Send email
        CorreoService.send_reset_token_email(
            to_email=user.email,
            token=token,
            user_name=user.full_name,
        )

        return True

    @classmethod
    def reset_password(cls, db: Session, email: str, token: str, new_password: str) -> bool:
        """Validate the reset token and update the user's password."""
        user = db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.email == email.lower().strip()).first()
        if not user:
            raise SolicitudInvalidaException(detail="Invalid or expired reset token")

        # Find the token in DB
        reset_token = (
            db.query(TokenRestablecimientoContrasena)
            .filter(
                TokenRestablecimientoContrasena.user_id == user.id,
                TokenRestablecimientoContrasena.token == token,
                TokenRestablecimientoContrasena.is_used == False,
            )
            .first()
        )

        if not reset_token:
            raise SolicitudInvalidaException(detail="Invalid or expired reset token")

        # Check expiration
        now = datetime.now(timezone.utc)
        token_expires = reset_token.expires_at
        if token_expires.tzinfo is None:
            token_expires = token_expires.replace(tzinfo=timezone.utc)

        if now > token_expires:
            reset_token.is_used = True
            db.commit()
            raise SolicitudInvalidaException(detail="Reset token has expired. Please request a new one")

        # Mark token as used
        reset_token.is_used = True

        # Update password
        user.hashed_password = get_password_hash(new_password)
        db.add(user)
        db.commit()

        return True

