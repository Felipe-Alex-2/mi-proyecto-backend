from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from app.core.validators import validate_required_string, validate_not_blank


class SupplierCreate(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=150)
    contact_name: str = Field(..., min_length=2, max_length=150)
    tax_id: Optional[str] = Field(None, max_length=50)
    email: EmailStr
    phone: str = Field(..., min_length=5, max_length=50)
    address: Optional[str] = Field(None, max_length=255)

    @field_validator("company_name")
    @classmethod
    def check_company_name(cls, v: str) -> str:
        return validate_required_string(v, "razón social del proveedor", 2)

    @field_validator("contact_name")
    @classmethod
    def check_contact_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre de contacto", 2)

    @field_validator("tax_id")
    @classmethod
    def check_tax_id(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "NIT o identificación tributaria")

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        return validate_required_string(v, "teléfono del proveedor", 5)

    @field_validator("address")
    @classmethod
    def check_address(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "dirección")


class SupplierUpdate(BaseModel):
    company_name: Optional[str] = Field(None, min_length=2, max_length=150)
    contact_name: Optional[str] = Field(None, min_length=2, max_length=150)
    tax_id: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, min_length=5, max_length=50)
    address: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None

    @field_validator("company_name")
    @classmethod
    def check_company_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "razón social del proveedor", 2)
        return v

    @field_validator("contact_name")
    @classmethod
    def check_contact_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "nombre de contacto", 2)
        return v

    @field_validator("tax_id")
    @classmethod
    def check_tax_id(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "NIT o identificación tributaria")

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "teléfono del proveedor", 5)
        return v

    @field_validator("address")
    @classmethod
    def check_address(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "dirección")


class SupplierResponse(BaseModel):
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
