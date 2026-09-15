from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
from app.core.validators import validate_required_string, validate_not_blank


class SeasonCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    start_date: date
    end_date: date

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre de la temporada", 2)

    @field_validator("description")
    @classmethod
    def check_description(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "descripción")

    @model_validator(mode="after")
    def check_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio")
        return self


class SeasonUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "nombre de la temporada", 2)
        return v

    @field_validator("description")
    @classmethod
    def check_description(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "descripción")

    @model_validator(mode="after")
    def check_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("La fecha de fin no puede ser anterior a la fecha de inicio")
        return self


class SeasonResponse(BaseModel):
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
