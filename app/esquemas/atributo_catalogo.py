from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator
from app.nucleo.validadores import validar_texto_obligatorio, validar_texto_opcional


# Categoria Schemas
class CategoriaCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "nombre de la categoría", 2)

    @field_validator("description")
    @classmethod
    def validar_descripcion(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "descripción")


class CategoriaUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "nombre de la categoría", 2)
        return v

    @field_validator("description")
    @classmethod
    def validar_descripcion(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "descripción")


class CategoriaResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Talla Schemas
class TallaCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    code: str = Field(..., min_length=1, max_length=20)
    category_type: Optional[str] = Field("GENERAL", max_length=50)

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "nombre de la talla", 1)

    @field_validator("code")
    @classmethod
    def validar_codigo(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "código de la talla", 1)

    @field_validator("category_type")
    @classmethod
    def validar_tipo_categoria(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "tipo de categoría")


class TallaUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    code: Optional[str] = Field(None, min_length=1, max_length=20)
    category_type: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "nombre de la talla", 1)
        return v

    @field_validator("code")
    @classmethod
    def validar_codigo(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "código de la talla", 1)
        return v

    @field_validator("category_type")
    @classmethod
    def validar_tipo_categoria(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "tipo de categoría")


class TallaResponse(BaseModel):
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
    def validar_nombre(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "nombre del color", 2)

    @field_validator("hex_code")
    @classmethod
    def validar_hexadecimal(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "código hexadecimal", 4)


class ColorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=50)
    hex_code: Optional[str] = Field(None, min_length=4, max_length=7, pattern=r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "nombre del color", 2)
        return v

    @field_validator("hex_code")
    @classmethod
    def validar_hexadecimal(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "código hexadecimal", 4)
        return v


class ColorResponse(BaseModel):
    id: str
    name: str
    hex_code: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
