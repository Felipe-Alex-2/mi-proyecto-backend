from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# Category Schemas
class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


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


class SizeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    code: Optional[str] = Field(None, min_length=1, max_length=20)
    category_type: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None


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


class ColorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=50)
    hex_code: Optional[str] = Field(None, min_length=4, max_length=7, pattern=r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
    is_active: Optional[bool] = None


class ColorResponse(BaseModel):
    id: str
    name: str
    hex_code: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
