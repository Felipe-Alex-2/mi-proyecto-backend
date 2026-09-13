from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
from app.models.user import UserRole
from app.core.validators import (
    validate_password_strength,
    validate_not_blank,
    validate_required_string,
)


class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    role: Optional[UserRole] = UserRole.ADMIN

    @field_validator("full_name")
    @classmethod
    def check_full_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre completo", 2)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "teléfono")


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    phone: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def check_full_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre completo", 2)

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "teléfono")


class UserCreateAdmin(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(..., description="Contraseña segura")
    role: UserRole = UserRole.CASHIER
    phone: Optional[str] = None
    branch_id: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def check_full_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre completo", 2)

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "teléfono")

    @field_validator("branch_id")
    @classmethod
    def check_branch_id(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "ID de sucursal")


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    password: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def check_full_name(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "nombre completo")

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "teléfono")

    @field_validator("password")
    @classmethod
    def check_password(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_password_strength(v)
        return v


class UserUpdateAdmin(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: Optional[UserRole] = None
    branch_id: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def check_full_name(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "nombre completo")

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "teléfono")

    @field_validator("branch_id")
    @classmethod
    def check_branch_id(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "ID de sucursal")

    @field_validator("password")
    @classmethod
    def check_password(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_password_strength(v)
        return v


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: str
    phone: Optional[str] = None
    branch_id: Optional[str] = None
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
