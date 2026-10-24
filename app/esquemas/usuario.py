from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
from app.modelos.usuario import RolUsuario
from app.nucleo.imagenes_perfil import normalize_profile_photo
from app.nucleo.validadores import (
    validar_seguridad_contrasena,
    validar_no_vacio,
    validar_texto_opcional,
    validar_texto_obligatorio,
)


class UsuarioBase(BaseModel):
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    role: Optional[RolUsuario] = RolUsuario.CUSTOMER

    @field_validator("full_name")
    @classmethod
    def validar_nombre_completo(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "nombre completo", 2)

    @field_validator("phone")
    @classmethod
    def validar_telefono(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "teléfono")


class UsuarioCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    phone: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def validar_nombre_completo(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "nombre completo", 2)

    @field_validator("password")
    @classmethod
    def validar_contrasena(cls, v: str) -> str:
        return validar_seguridad_contrasena(v)

    @field_validator("phone")
    @classmethod
    def validar_telefono(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "teléfono")


class UsuarioCreateAdmin(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(..., description="Contraseña segura")
    role: RolUsuario = RolUsuario.CASHIER
    phone: Optional[str] = None
    branch_id: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def validar_nombre_completo(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "nombre completo", 2)

    @field_validator("password")
    @classmethod
    def validar_contrasena(cls, v: str) -> str:
        return validar_seguridad_contrasena(v)

    @field_validator("phone")
    @classmethod
    def validar_telefono(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "teléfono")

    @field_validator("branch_id")
    @classmethod
    def validar_id_sucursal(cls, v: Optional[str]) -> Optional[str]:
        return validar_no_vacio(v, "ID de sucursal")


class ImagenPerfilUpdate(BaseModel):
    avatar_id: Optional[Literal['terracotta', 'sage', 'sand']] = None
    profile_photo: Optional[str] = Field(None, max_length=700000)

    @field_validator('profile_photo')
    @classmethod
    def validar_foto(cls, value):
        return normalize_profile_photo(value)


class UsuarioUpdate(ImagenPerfilUpdate):
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    password: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def validar_nombre_completo(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_obligatorio(v, "nombre completo", 2) if v is not None else v

    @field_validator("phone")
    @classmethod
    def validar_telefono(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "teléfono")

    @field_validator("password")
    @classmethod
    def validar_contrasena(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip():
            return validar_seguridad_contrasena(v)
        return None


class UsuarioUpdateAdmin(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: Optional[RolUsuario] = None
    branch_id: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def validar_nombre_completo(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_obligatorio(v, "nombre completo", 2) if v is not None else v

    @field_validator("phone")
    @classmethod
    def validar_telefono(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "teléfono")

    @field_validator("branch_id")
    @classmethod
    def validar_id_sucursal(cls, v: Optional[str]) -> Optional[str]:
        return validar_no_vacio(v, "ID de sucursal")

    @field_validator("password")
    @classmethod
    def validar_contrasena(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip():
            return validar_seguridad_contrasena(v)
        return None


class UsuarioResponse(BaseModel):
    company_name: Optional[str] = None
    branch_name: Optional[str] = None
    tenant_id: Optional[str] = None
    selected_tenant_id: Optional[str] = None
    is_saas_admin: bool = False
    avatar_id: str = 'terracotta'
    profile_photo: Optional[str] = None
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

    @classmethod
    def for_context(cls, db, user):
        response = cls.model_validate(user)
        if user.role == 'CUSTOMER' and db.info.get('tenant_context'):
            from app.modelos.saas import Empresa
            from app.modelos.sucursal import Sucursal
            tenant_id = db.info.get('tenant_id')
            branch_id = db.info.get('customer_branch_id')
            company = db.get(Empresa, tenant_id) if tenant_id else None
            branch = db.query(Sucursal).execution_options(skip_tenant=True).filter(Sucursal.id == branch_id, Sucursal.tenant_id == tenant_id).first() if branch_id else None
            return response.model_copy(update={'selected_tenant_id':tenant_id, 'branch_id':branch_id,
                'company_name':company.name if company else None, 'branch_name':branch.name if branch else None})
        return response
