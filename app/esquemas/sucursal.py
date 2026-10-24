from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.nucleo.validadores import validar_texto_obligatorio, validar_texto_opcional


class SucursalBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    city: str = Field(..., min_length=2, max_length=100)
    address: str = Field(..., min_length=5, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    opening_hours: Optional[str] = Field(None, max_length=100)

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "nombre de la sucursal", 2)

    @field_validator("city")
    @classmethod
    def validar_ciudad(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "ciudad", 2)

    @field_validator("address")
    @classmethod
    def validar_direccion(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "dirección", 5)

    @field_validator("phone")
    @classmethod
    def validar_telefono(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "teléfono")

    @field_validator("opening_hours")
    @classmethod
    def validar_horario(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "horario de atención")


class SucursalCreate(SucursalBase):
    pass


class SucursalUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    city: Optional[str] = Field(None, min_length=2, max_length=100)
    address: Optional[str] = Field(None, min_length=5, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    opening_hours: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "nombre de la sucursal", 2)
        return v

    @field_validator("city")
    @classmethod
    def validar_ciudad(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "ciudad", 2)
        return v

    @field_validator("address")
    @classmethod
    def validar_direccion(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "dirección", 5)
        return v

    @field_validator("phone")
    @classmethod
    def validar_telefono(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "teléfono")

    @field_validator("opening_hours")
    @classmethod
    def validar_horario(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "horario de atención")


class PersonalSucursal(BaseModel):
    id: str
    full_name: str
    email: str
    role: str
    phone: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SucursalResponse(SucursalBase):
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    staff_count: int = 0
    manager: Optional[PersonalSucursal] = None
    cashiers: List[PersonalSucursal] = []

    model_config = ConfigDict(from_attributes=True)


class AsignarPersonalRequest(BaseModel):
    user_ids: List[str] = Field(..., min_length=1, description="Lista de IDs de usuarios a asignar a la sucursal")
