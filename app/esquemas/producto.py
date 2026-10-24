from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.esquemas.stock import StockResponse
from app.nucleo.validadores import validar_texto_obligatorio, validar_no_vacio, validar_texto_opcional


class VarianteCreate(BaseModel):
    size_id: str
    color_id: str
    sku: Optional[str] = Field(None, max_length=60)
    price_override: Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    initial_stock: Optional[Dict[str, int]] = Field(default_factory=dict, description="Diccionario branch_id -> cantidad")

    @field_validator("size_id")
    @classmethod
    def validar_id_talla(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "ID de talla", 1)

    @field_validator("color_id")
    @classmethod
    def validar_id_color(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "ID de color", 1)

    @field_validator('initial_stock')
    @classmethod
    def validar_stock(cls, value):
        if value and any(not key.strip() or quantity < 0 for key, quantity in value.items()):
            raise ValueError('El stock requiere sucursales válidas y cantidades no negativas.')
        return value

    @field_validator("sku")
    @classmethod
    def validar_sku(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "código SKU")


class VarianteProductoResponse(BaseModel):
    id: str
    product_id: str
    size_id: str
    color_id: str
    sku: str
    price_override: Optional[float] = None
    is_active: bool
    size_code: Optional[str] = None
    size_name: Optional[str] = None
    color_name: Optional[str] = None
    color_hex: Optional[str] = None
    total_stock: int = 0
    stocks: List[StockResponse] = []

    model_config = ConfigDict(from_attributes=True)


class ProductoCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    description: Optional[str] = None
    price: float = Field(..., gt=0, allow_inf_nan=False)
    category_id: str
    season_id: Optional[str] = None
    supplier_id: Optional[str] = None
    promotion_id: Optional[str] = None
    image_url: Optional[str] = None
    gender: str = Field("UNISEX", description="HOMBRE, MUJER, UNISEX, NIÑOS")
    variants: List[VarianteCreate] = Field(default_factory=list)

    @field_validator('season_id', 'supplier_id', 'promotion_id', mode='before')
    @classmethod
    def validar_referencias_catalogo_opcionales(cls, value):
        return validar_texto_opcional(value)

    @model_validator(mode='after')
    def validar_variantes_duplicadas(self):
        combinations = [(v.size_id, v.color_id) for v in self.variants]
        skus = [v.sku.casefold() for v in self.variants if v.sku]
        if len(set(combinations)) != len(combinations) or len(set(skus)) != len(skus):
            raise ValueError('No repitas la combinación de talla/color ni el SKU de las variantes.')
        return self

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "nombre de la prenda", 2)

    @field_validator("category_id")
    @classmethod
    def validar_id_categoria(cls, v: str) -> str:
        return validar_texto_obligatorio(v, "categoría", 1)

    @field_validator("description")
    @classmethod
    def validar_descripcion(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "descripción")

    @field_validator("image_url")
    @classmethod
    def validar_url_imagen(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "URL de imagen")


class ProductoUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    description: Optional[str] = None
    price: Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    category_id: Optional[str] = None
    season_id: Optional[str] = None
    supplier_id: Optional[str] = None
    promotion_id: Optional[str] = None
    image_url: Optional[str] = None
    gender: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator('season_id', 'supplier_id', 'promotion_id', mode='before')
    @classmethod
    def validar_referencias_catalogo_opcionales(cls, value):
        return validar_texto_opcional(value)

    @field_validator("name")
    @classmethod
    def validar_nombre(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validar_texto_obligatorio(v, "nombre de la prenda", 2)
        return v

    @field_validator("category_id")
    @classmethod
    def validar_id_categoria(cls, v: Optional[str]) -> Optional[str]:
        return validar_no_vacio(v, "categoría")

    @field_validator("description")
    @classmethod
    def validar_descripcion(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "descripción")

    @field_validator("gender")
    @classmethod
    def validar_genero(cls, v: Optional[str]) -> Optional[str]:
        return validar_no_vacio(v, "género")

    @field_validator("image_url")
    @classmethod
    def validar_url_imagen(cls, v: Optional[str]) -> Optional[str]:
        return validar_texto_opcional(v, "URL de imagen")


class ProductoResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    price: float
    category_id: str
    category_name: Optional[str] = None
    season_id: Optional[str] = None
    season_name: Optional[str] = None
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    promotion_id: Optional[str] = None
    promotion_name: Optional[str] = None
    discount_percent: Optional[float] = None
    image_url: Optional[str] = None
    gender: str
    is_active: bool
    total_stock: int = 0
    variants: List[VarianteProductoResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
