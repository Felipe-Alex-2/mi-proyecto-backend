from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
from app.core.validators import validate_required_string, validate_not_blank


class PromotionCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    discount_percent: float = Field(..., gt=0, le=100, description="Porcentaje de descuento entre 1 y 100")
    start_date: date
    end_date: date

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre de la promoción", 2)

    @field_validator("description")
    @classmethod
    def check_description(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "descripción")

    @field_validator("discount_percent")
    @classmethod
    def check_discount(cls, v: float) -> float:
        if v <= 0 or v > 100:
            raise ValueError("El porcentaje de descuento debe ser mayor a 0 y menor o igual a 100")
        return round(v, 2)

    @model_validator(mode="after")
    def check_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio")
        return self


class PromotionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    discount_percent: Optional[float] = Field(None, gt=0, le=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "nombre de la promoción", 2)
        return v

    @field_validator("description")
    @classmethod
    def check_description(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "descripción")

    @field_validator("discount_percent")
    @classmethod
    def check_discount(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if v <= 0 or v > 100:
                raise ValueError("El porcentaje de descuento debe ser mayor a 0 y menor o igual a 100")
            return round(v, 2)
        return v

    @model_validator(mode="after")
    def check_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio")
        return self


class PromotionResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    discount_percent: float
    start_date: date
    end_date: date
    is_active: bool
    is_expired: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
