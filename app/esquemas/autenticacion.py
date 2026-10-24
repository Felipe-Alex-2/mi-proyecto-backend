from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator
from app.esquemas.usuario import UsuarioResponse
from app.nucleo.validadores import (
    validar_seguridad_contrasena,
    validar_texto_opcional,
    validar_texto_obligatorio,
)


class RegistroRequest(BaseModel):
    tenant_id: Optional[str] = None
    branch_id: Optional[str] = None
    email: EmailStr
    password: str = Field(..., description="Contraseña segura (mínimo 8 caracteres, mayúscula, minúscula, número y símbolo)")
    full_name: str = Field(..., min_length=2, max_length=100)
    phone: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validar_contrasena(cls, v: str) -> str:
        return validar_seguridad_contrasena(v)

    @field_validator("full_name")
    @classmethod
    def validar_nombre_completo(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "nombre completo", 2)

    @field_validator("phone")
    @classmethod
    def validar_telefono(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "teléfono")


class InicioSesionRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validar_contrasena_no_vacia(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "contraseña", 1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # in seconds
    user: UsuarioResponse


class RenovarTokenRequest(BaseModel):
    refresh_token: str

    @field_validator("refresh_token")
    @classmethod
    def validar_renovacion_token(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "token de refresco", 1)


class TokenPayload(BaseModel):
    sub: str  # user id
    email: Optional[str] = None
    type: str = "access"  # "access" or "refresh"
    exp: int
    iat: int


class RecuperarContrasenaRequest(BaseModel):
    email: EmailStr


class RestablecerContrasenaRequest(BaseModel):
    email: EmailStr
    token: str = Field(..., min_length=6, max_length=6, description="6-digit reset token")
    new_password: str = Field(..., description="Nueva contraseña segura")

    @field_validator("token")
    @classmethod
    def validar_token(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "código de restablecimiento", 6)

    @field_validator("new_password")
    @classmethod
    def validar_nueva_contrasena(cls, v: str) -> str:
        return validar_seguridad_contrasena(v)
