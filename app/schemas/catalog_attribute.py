from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator
from app.core.validators import validate_required_string, validate_not_blank


# Category Schemas
class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre de la categoría", 2)

    @field_validator("description")
    @classmethod
    def check_description(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "descripción")


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "nombre de la categoría", 2)
        return v

    @field_validator("description")
    @classmethod
    def check_description(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "descripción")


class CategoryResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Size Schemas
class SizeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    code: str = Field(..., min_length=1, max_length=20)
    category_type: Optional[str] = Field("GENERAL", max_length=50)

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre de la talla", 1)

    @field_validator("code")
    @classmethod
    def check_code(cls, v: str) -> str:
        return validate_required_string(v, "código de la talla", 1)

    @field_validator("category_type")
    @classmethod
    def check_category_type(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "tipo de categoría")


class SizeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    code: Optional[str] = Field(None, min_length=1, max_length=20)
    category_type: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "nombre de la talla", 1)
        return v

    @field_validator("code")
    @classmethod
    def check_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "código de la talla", 1)
        return v

    @field_validator("category_type")
    @classmethod
    def check_category_type(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "tipo de categoría")


class SizeResponse(BaseModel):
    id: str
    name: str
    code: str
    category_type: Optional[str] = "GENERAL"
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Color Schemas
class ColorCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    hex_code: str = Field(..., min_length=4, max_length=7, pattern=r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre del color", 2)

    @field_validator("hex_code")
    @classmethod
    def check_hex(cls, v: str) -> str:
        return validate_required_string(v, "código hexadecimal", 4)


class ColorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=50)
    hex_code: Optional[str] = Field(None, min_length=4, max_length=7, pattern=r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "nombre del color", 2)
        return v

    @field_validator("hex_code")
    @classmethod
    def check_hex(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "código hexadecimal", 4)
        return v


class ColorResponse(BaseModel):
    id: str
    name: str
    hex_code: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
