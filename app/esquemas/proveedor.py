from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from app.nucleo.validadores import validar_texto_obligatorio, validar_texto_opcional


class ProveedorCreate(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=150)
    contact_name: str = Field(..., min_length=2, max_length=150)
    tax_id: Optional[str] = Field(None, max_length=50)
    email: EmailStr
    phone: str = Field(..., min_length=5, max_length=50)
    address: Optional[str] = Field(None, max_length=255)

    @field_validator("company_name")
    @classmethod
    def validar_nombre_empresa(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "razón social del proveedor", 2)

    @field_validator("contact_name")
    @classmethod
    def validar_nombre_contacto(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "nombre de contacto", 2)

    @field_validator("tax_id")
    @classmethod
    def validar_identificacion_fiscal(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "NIT o identificación tributaria")

    @field_validator("phone")
    @classmethod
    def validar_telefono(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "teléfono del proveedor", 5)

    @field_validator("address")
    @classmethod
    def validar_direccion(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "dirección")


class ProveedorUpdate(BaseModel):
    company_name: Optional[str] = Field(None, min_length=2, max_length=150)
    contact_name: Optional[str] = Field(None, min_length=2, max_length=150)
    tax_id: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, min_length=5, max_length=50)
    address: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None

    @field_validator("company_name")
    @classmethod
    def validar_nombre_empresa(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "razón social del proveedor", 2)
        return v

    @field_validator("contact_name")
    @classmethod
    def validar_nombre_contacto(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "nombre de contacto", 2)
        return v

    @field_validator("tax_id")
    @classmethod
    def validar_identificacion_fiscal(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "NIT o identificación tributaria")

    @field_validator("phone")
    @classmethod
    def validar_telefono(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "teléfono del proveedor", 5)
        return v

    @field_validator("address")
    @classmethod
    def validar_direccion(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "dirección")


class ProveedorResponse(BaseModel):
    id: str
    company_name: str
    contact_name: str
    tax_id: Optional[str] = None
    email: str
    phone: str
    address: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
