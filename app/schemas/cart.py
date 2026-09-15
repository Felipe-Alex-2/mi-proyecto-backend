from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class CartItemAdd(BaseModel):
    variant_id: str = Field(..., description="ID de la variante seleccionada")
    quantity: int = Field(1, ge=1, description="Cantidad a agregar (mínimo 1)")


class CartItemUpdate(BaseModel):
    quantity: int = Field(..., ge=1, description="Nueva cantidad (mínimo 1)")


class CartItemResponse(BaseModel):
    id: str
    variant_id: str
    quantity: int
    added_at: datetime
    updated_at: datetime

    # Presentation fields
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    sku: Optional[str] = None
    size_name: Optional[str] = None
    color_name: Optional[str] = None
    color_hex: Optional[str] = None
    price: float = 0.0
    subtotal: float = 0.0
    image_url: Optional[str] = None
    available_stock: int = 0

    model_config = ConfigDict(from_attributes=True)


class CartResponse(BaseModel):
    items: List[CartItemResponse] = []
    total_items: int = 0
    total_amount: float = 0.0
