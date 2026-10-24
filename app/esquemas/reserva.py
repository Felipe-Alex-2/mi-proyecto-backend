from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.modelos.reserva import EstadoReserva


class ReservaItemCreate(BaseModel):
    variant_id: str = Field(..., description="ID de la variante")
    quantity: int = Field(1, ge=1, le=50, description="Cantidad a reservar")


class ReservaCreate(BaseModel):
    branch_id: str = Field(..., description="Sucursal donde se realizará la prueba")
    items: List[ReservaItemCreate] = Field(..., min_length=1, max_length=50, description="Prendas a reservar")
    customer_notes: Optional[str] = Field(None, max_length=500, description="Notas o comentarios del cliente")
    payment_method: Optional[Literal["EFECTIVO", "PAYPAL"]] = Field("EFECTIVO", description="Método de pago: EFECTIVO o PAYPAL")


class EstadoReservaUpdate(BaseModel):
    status: EstadoReserva = Field(..., description="Nuevo estado")
    staff_notes: Optional[str] = Field(None, max_length=500, description="Nota obligatoria para completar o cancelar")
    payment_method: Optional[str] = Field(None, description="Método de pago (EFECTIVO, PAYPAL)")
    payment_status: Optional[str] = Field(None, description="Estado de pago (PENDING, PAID)")


class ReservaItemResponse(BaseModel):
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
    original_price: Optional[float] = None
    discount_percent: Optional[float] = None
    image_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ReservaResponse(BaseModel):
    tenant_id: Optional[str] = None
    company_name: Optional[str] = None
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

    # Pago tracking
    payment_method: Optional[str] = "EFECTIVO"
    payment_status: str = "PENDING"
    paypal_order_id: Optional[str] = None
    paypal_capture_id: Optional[str] = None
    paid_at: Optional[datetime] = None
    total_amount: Optional[float] = None

    items: List[ReservaItemResponse] = []
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    branch_name: Optional[str] = None
    branch_address: Optional[str] = None
    total_items: int = 0
    total_estimated_amount: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class OrdenReservaPayPalCreate(BaseModel):
    branch_id: str = Field(..., description="Sucursal donde se retirará la reserva")
    items: List[ReservaItemCreate] = Field(..., min_length=1, max_length=50, description="Prendas a pagar/reservar")
    customer_notes: Optional[str] = Field(None, max_length=500, description="Notas del cliente")
    return_url: Optional[str] = Field(None, description="URL de retorno para checkout web")
    cancel_url: Optional[str] = Field(None, description="URL de cancelación")


class OrdenPayPalResponse(BaseModel):
    order_id: str
    approval_url: str
    reservation: ReservaResponse


class CapturaPayPalRequest(BaseModel):
    paypal_order_id: Optional[str] = Field(None, description="ID de orden emitida por PayPal")
    order_id: Optional[str] = Field(None, description="ID de orden emitida por PayPal (alias móvil)")

    @model_validator(mode="after")
    def resolve_order_id(self):
        resolved = self.paypal_order_id or self.order_id
        if not resolved:
            raise ValueError("paypal_order_id u order_id es requerido")
        self.paypal_order_id = resolved
        return self


class CapturaPayPalResponse(BaseModel):
    order_id: str
    capture_id: Optional[str] = None
    status: str
    reservation: ReservaResponse


class EstadisticasReservaResponse(BaseModel):
    total: int = 0
    pending: int = 0
    confirmed: int = 0
    completed: int = 0
    cancelled: int = 0
    expired: int = 0
    conversion_rate: float = 0.0
