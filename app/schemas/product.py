from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.schemas.stock import StockResponse
from app.core.validators import validate_required_string, validate_not_blank


class VariantCreate(BaseModel):
    size_id: str
    color_id: str
    sku: Optional[str] = Field(None, max_length=60)
    price_override: Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    initial_stock: Optional[Dict[str, int]] = Field(default_factory=dict, description="Diccionario branch_id -> cantidad")

    @field_validator("size_id")
    @classmethod
    def check_size_id(cls, v: str) -> str:
        return validate_required_string(v, "ID de talla", 1)

    @field_validator("color_id")
    @classmethod
    def check_color_id(cls, v: str) -> str:
        return validate_required_string(v, "ID de color", 1)

    @field_validator('initial_stock')
    @classmethod
    def check_stock(cls, value):
        if value and any(not key.strip() or quantity < 0 for key, quantity in value.items()):
            raise ValueError('El stock requiere sucursales válidas y cantidades no negativas.')
        return value

    @field_validator("sku")
    @classmethod
    def check_sku(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "código SKU")


class ProductVariantResponse(BaseModel):
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


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    description: Optional[str] = None
    price: float = Field(..., gt=0, allow_inf_nan=False)
    category_id: str
    season_id: Optional[str] = None
    supplier_id: Optional[str] = None
    promotion_id: Optional[str] = None
    image_url: Optional[str] = None
    gender: str = Field("UNISEX", description="HOMBRE, MUJER, UNISEX, NIÑOS")
    variants: List[VariantCreate] = Field(default_factory=list)

    @model_validator(mode='after')
    def check_duplicate_variants(self):
        combinations = [(v.size_id, v.color_id) for v in self.variants]
        skus = [v.sku.casefold() for v in self.variants if v.sku]
        if len(set(combinations)) != len(combinations) or len(set(skus)) != len(skus):
            raise ValueError('No repitas la combinación de talla/color ni el SKU de las variantes.')
        return self

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return validate_required_string(v, "nombre de la prenda", 2)

    @field_validator("category_id")
    @classmethod
    def check_category_id(cls, v: str) -> str:
        return validate_required_string(v, "categoría", 1)

    @field_validator("description")
    @classmethod
    def check_description(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "descripción")

    @field_validator("image_url")
    @classmethod
    def check_image_url(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "URL de imagen")


class ProductUpdate(BaseModel):
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

    @field_validator("name")
    @classmethod
    def check_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_required_string(v, "nombre de la prenda", 2)
        return v

    @field_validator("category_id")
    @classmethod
    def check_category_id(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "categoría")

    @field_validator("description")
    @classmethod
    def check_description(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "descripción")

    @field_validator("gender")
    @classmethod
    def check_gender(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "género")

    @field_validator("image_url")
    @classmethod
    def check_image_url(cls, v: Optional[str]) -> Optional[str]:
        return validate_not_blank(v, "URL de imagen")


class ProductResponse(BaseModel):
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
    variants: List[ProductVariantResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
