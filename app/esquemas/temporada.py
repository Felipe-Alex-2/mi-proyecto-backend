from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
from app.nucleo.validadores import validar_texto_obligatorio, validar_texto_opcional


class TemporadaCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    start_date: date
    end_date: date

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "nombre de la temporada", 2)

    @field_validator("description")
    @classmethod
    def validar_descripcion(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "descripción")

    @model_validator(mode="after")
    def validar_fechas(self):
        if self.end_date < self.start_date:
            raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio")
        return self


class TemporadaUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "nombre de la temporada", 2)
        return v

    @field_validator("description")
    @classmethod
    def validar_descripcion(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "descripción")

    @model_validator(mode="after")
    def validar_fechas(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio")
        return self


class TemporadaResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    start_date: date
    end_date: date
    is_active: bool
    is_expired: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
