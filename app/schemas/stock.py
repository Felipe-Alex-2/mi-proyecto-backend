from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class StockResponse(BaseModel):
    id: str
    variant_id: str
    branch_id: str
    quantity: int
    min_alert_threshold: int
    updated_at: datetime
    branch_name: Optional[str] = None
    branch_city: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class StockAdjustRequest(BaseModel):
    variant_id: str
    branch_id: str
    quantity: int = Field(..., ge=0, description="Cantidad en existencia")


class BranchInventoryItem(BaseModel):
    variant_id: str
    product_id: str
    product_name: str
    category_name: str
    sku: str
    size_code: str
    size_name: str
    color_name: str
    color_hex: str
    price: float
    quantity: int
    min_alert_threshold: int
    is_low_stock: bool
