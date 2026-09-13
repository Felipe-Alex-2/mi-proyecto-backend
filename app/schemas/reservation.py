from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field
from app.models.reservation import ReservationStatus


class ReservationItemCreate(BaseModel):
    variant_id: str = Field(..., description="ID de la variante")
    quantity: int = Field(1, ge=1, le=5, description="Cantidad a reservar (1 a 5 por item)")


class ReservationCreate(BaseModel):
    branch_id: str = Field(..., description="Sucursal donde se realizará la prueba")
    items: List[ReservationItemCreate] = Field(..., min_length=1, max_length=10, description="Prendas a reservar")
    customer_notes: Optional[str] = Field(None, max_length=500, description="Notas o comentarios del cliente")


class ReservationStatusUpdate(BaseModel):
    status: ReservationStatus = Field(..., description="Nuevo estado")
    staff_notes: Optional[str] = Field(None, max_length=500, description="Nota obligatoria para completar o cancelar")


class ReservationItemResponse(BaseModel):
    id: str
    variant_id: str
    quantity: int
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    sku: Optional[str] = None
    size_name: Optional[str] = None
    color_name: Optional[str] = None
    color_hex: Optional[str] = None
    price: float = 0.0
    image_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ReservationResponse(BaseModel):
    id: str
    reservation_code: str
    customer_id: str
    branch_id: str
    status: str
    customer_notes: Optional[str] = None
    staff_notes: Optional[str] = None
    staff_user_id: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    updated_at: datetime

    items: List[ReservationItemResponse] = []
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    branch_name: Optional[str] = None
    branch_address: Optional[str] = None
    total_items: int = 0
    total_estimated_amount: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class ReservationStatsResponse(BaseModel):
    total: int = 0
    pending: int = 0
    confirmed: int = 0
    completed: int = 0
    cancelled: int = 0
    expired: int = 0
    conversion_rate: float = 0.0
