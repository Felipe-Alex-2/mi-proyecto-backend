from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class PaymentBase(BaseModel):
    customer_name: str = Field(..., min_length=2, max_length=150, description="Nombre del cliente")
    customer_email: Optional[str] = Field(None, max_length=150, description="Correo electrónico opcional")
    concept: str = Field(..., min_length=2, max_length=255, description="Concepto del cobro")
    amount: float = Field(..., gt=0, description="Monto total a cobrar")
    currency: str = Field("USD", description="Moneda (USD, BOB, EUR)")
    payment_type: str = Field("EFECTIVO", description="Tipo de pago: EFECTIVO o PAYPAL")
    notes: Optional[str] = Field(None, description="Notas adicionales")


class PaymentItemCreate(BaseModel):
    variant_id: str = Field(..., description="ID de la variante de producto")
    quantity: int = Field(..., gt=0, description="Cantidad a vender")
    unit_price: float = Field(..., ge=0, description="Precio unitario")
    subtotal: Optional[float] = Field(None, description="Subtotal de la línea")
    product_name: Optional[str] = Field(None, description="Nombre del producto")
    sku: Optional[str] = Field(None, description="SKU de la variante")
    size: Optional[str] = Field(None, description="Talla")
    color: Optional[str] = Field(None, description="Color")


class PaymentCreate(PaymentBase):
    branch_id: str = Field(..., description="ID de la sucursal de cobro")
    reservation_id: Optional[str] = Field(None, description="ID de la reserva vinculada si aplica")
    items: Optional[List[PaymentItemCreate]] = Field(None, description="Detalle de productos vendidos en caja")


class PaymentProcess(BaseModel):
    payment_type: Optional[str] = Field(None, description="EFECTIVO o PAYPAL")
    notes: Optional[str] = Field(None, description="Notas de cobro")


class PaymentResponse(BaseModel):
    id: str
    payment_code: str
    branch_id: str
    branch_name: Optional[str] = None
    reservation_id: Optional[str] = None
    reservation_code: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: str
    customer_email: Optional[str] = None
    concept: str
    amount: float
    currency: str
    payment_type: str
    status: str
    reference: Optional[str] = None
    paypal_order_id: Optional[str] = None
    paypal_capture_id: Optional[str] = None
    cashier_id: Optional[str] = None
    cashier_name: Optional[str] = None
    items_detail: Optional[str] = None
    items: Optional[List[Dict[str, Any]]] = None
    notes: Optional[str] = None
    created_at: datetime
    paid_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PaymentPayPalOrderResponse(BaseModel):
    payment_id: str
    order_id: str
    approval_url: str
    amount: float
    currency: str


class PendingReservationOption(BaseModel):
    reservation_id: str
    reservation_code: str
    customer_name: str
    customer_email: Optional[str] = None
    branch_id: str
    branch_name: Optional[str] = None
    total_items: int
    total_amount: float
    items_summary: str
    status: str
    payment_status: str
