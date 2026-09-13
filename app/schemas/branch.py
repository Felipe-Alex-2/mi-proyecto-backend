from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.core.validators import validate_required_string, validate_not_blank


class BranchBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    city: str = Field(..., min_length=2, max_length=100)
    address: str = Field(..., min_length=5, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    opening_hours: Optional[str] = Field(None, max_length=100)

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre de la sucursal", 2)

    @field_validator("city")
    @classmethod
    def check_city(cls, v: str) -> str:
        return validate_required_string(v, "ciudad", 2)

    @field_validator("address")
    @classmethod
    def check_address(cls, v: str) -> str:
        return validate_required_string(v, "dirección", 5)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "teléfono")

    @field_validator("opening_hours")
    @classmethod
    def check_opening_hours(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "horario de atención")


class BranchCreate(BranchBase):
    pass


class BranchUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    city: Optional[str] = Field(None, min_length=2, max_length=100)
    address: Optional[str] = Field(None, min_length=5, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    opening_hours: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "nombre de la sucursal", 2)
        return v

    @field_validator("city")
    @classmethod
    def check_city(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "ciudad", 2)
        return v

    @field_validator("address")
    @classmethod
    def check_address(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "dirección", 5)
        return v

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "teléfono")

    @field_validator("opening_hours")
    @classmethod
    def check_opening_hours(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "horario de atención")


class BranchStaffMember(BaseModel):
    id: str
    full_name: str
    email: str
    role: str
    phone: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class BranchResponse(BranchBase):
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    staff_count: int = 0
    manager: Optional[BranchStaffMember] = None
    cashiers: List[BranchStaffMember] = []

    model_config = ConfigDict(from_attributes=True)


class AssignStaffRequest(BaseModel):
    user_ids: List[str] = Field(..., min_length=1, description="Lista de IDs de usuarios a asignar a la sucursal")
