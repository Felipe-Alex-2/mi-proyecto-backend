from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict


class CatalogFilterOptions(BaseModel):
    categories: List[Dict[str, Any]] = []
    sizes: List[Dict[str, Any]] = []
    colors: List[Dict[str, Any]] = []
    seasons: List[Dict[str, Any]] = []
    branches: List[Dict[str, Any]] = []
    genders: List[str] = ["Hombre", "Mujer", "Unisex", "Niños"]
    min_price: float = 0.0
    max_price: float = 1000.0


class CatalogVariantBranchStock(BaseModel):
    branch_id: str
    branch_name: str
    branch_city: str
    quantity: int
    status: str  # "IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"


class CatalogProductVariantResponse(BaseModel):
    id: str
    size_id: str
    size_name: str
    size_code: str
    color_id: str
    color_name: str
    color_hex: str
    sku: str
    price: float
    total_stock: int
    branch_availability: List[CatalogVariantBranchStock] = []

    model_config = ConfigDict(from_attributes=True)


class CatalogProductDetailResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    season_id: Optional[str] = None
    season_name: Optional[str] = None
    gender: Optional[str] = None
    image_url: Optional[str] = None
    min_price: float = 0.0
    max_price: float = 0.0
    total_stock: int = 0
    variants: List[CatalogProductVariantResponse] = []
    colors: List[Dict[str, str]] = []
    sizes: List[Dict[str, str]] = []

    model_config = ConfigDict(from_attributes=True)


class CatalogProductListResponse(BaseModel):
    items: List[CatalogProductDetailResponse] = []
    total: int = 0
    page: int = 1
    page_size: int = 20
