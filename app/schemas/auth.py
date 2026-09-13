from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator
from app.schemas.user import UserResponse
from app.core.validators import (
    validate_password_strength,
    validate_not_blank,
    validate_required_string,
)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., description="Contraseña segura (mínimo 8 caracteres, mayúscula, minúscula, número y símbolo)")
    full_name: str = Field(..., min_length=2, max_length=100)
    phone: Optional[str] = None

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v)

    @field_validator("full_name")
    @classmethod
    def check_full_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre completo", 2)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "teléfono")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def check_password_not_empty(cls, v: str) -> str:
        return validate_required_string(v, "contraseña", 1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # in seconds
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    refresh_token: str

    @field_validator("refresh_token")
    @classmethod
    def check_refresh_token(cls, v: str) -> str:
        return validate_required_string(v, "token de refresco", 1)


class TokenPayload(BaseModel):
    sub: str  # user id
    email: Optional[str] = None
    type: str = "access"  # "access" or "refresh"
    exp: int
    iat: int


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    token: str = Field(..., min_length=6, max_length=6, description="6-digit reset token")
    new_password: str = Field(..., description="Nueva contraseña segura")

    @field_validator("token")
    @classmethod
    def check_token(cls, v: str) -> str:
        return validate_required_string(v, "código de restablecimiento", 6)

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, v: str) -> str:
        return validate_password_strength(v)
