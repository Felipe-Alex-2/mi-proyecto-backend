from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field
from app.models.inventory_movement import MovementType


class InventoryMovementCreate(BaseModel):
    variant_id: str = Field(..., description="ID de la variante de producto")
    branch_id: str = Field(..., description="ID de la sucursal")
    type: MovementType = Field(..., description="Tipo de movimiento: ENTRY, EXIT, ADJUSTMENT, RETURN")
    quantity: int = Field(..., ge=1, description="Cantidad a mover (entero positivo mayor o igual a 1)")
    reason: str = Field(..., min_length=5, max_length=255, description="Motivo del movimiento")
    reference_number: Optional[str] = Field(None, max_length=100, description="Número de referencia/guía/factura")


class InventoryMovementUpdate(BaseModel):
    reason: Optional[str] = Field(None, min_length=5, max_length=255, description="Motivo corregido")
    reference_number: Optional[str] = Field(None, max_length=100, description="Número de referencia/guía corregido")


class InventoryMovementResponse(BaseModel):
    id: str
    variant_id: str
    branch_id: str
    type: str
    quantity: int
    reason: str
    reference_number: Optional[str] = None
    previous_stock: int
    new_stock: int
    user_id: Optional[str] = None
    created_at: datetime
    
    # Optional enriched presentation fields
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    sku: Optional[str] = None
    size_name: Optional[str] = None
    color_name: Optional[str] = None
    branch_name: Optional[str] = None
    user_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class BranchInventorySummary(BaseModel):
    branch_id: str
    branch_name: str
    total_variants: int
    total_units: int
    low_stock_count: int
    out_of_stock_count: int


class VariantBranchAvailability(BaseModel):
    branch_id: str
    branch_name: str
    branch_city: str
    branch_address: str
    quantity: int
    status: str  # "IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"
