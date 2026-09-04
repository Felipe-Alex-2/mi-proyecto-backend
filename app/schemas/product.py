from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.stock import StockResponse


class VariantCreate(BaseModel):
    size_id: str
    color_id: str
    sku: Optional[str] = None
    price_override: Optional[float] = None
    initial_stock: Optional[Dict[str, int]] = Field(default_factory=dict, description="Diccionario branch_id -> cantidad")


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
    price: float = Field(..., gt=0)
    category_id: str
    season_id: Optional[str] = None
    supplier_id: Optional[str] = None
    image_url: Optional[str] = None
    gender: str = Field("UNISEX", description="HOMBRE, MUJER, UNISEX, NIÑOS")
    variants: List[VariantCreate] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    description: Optional[str] = None
    price: Optional[float] = Field(None, gt=0)
    category_id: Optional[str] = None
    season_id: Optional[str] = None
    supplier_id: Optional[str] = None
    image_url: Optional[str] = None
    gender: Optional[str] = None
    is_active: Optional[bool] = None


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
    image_url: Optional[str] = None
    gender: str
    is_active: bool
    total_stock: int = 0
    variants: List[ProductVariantResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
