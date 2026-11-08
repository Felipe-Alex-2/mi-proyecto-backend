from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Solicitud(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_id: UUID


class CambioCreate(Solicitud):
    payment_id: str | None = Field(default=None, min_length=1, max_length=36)
    reservation_id: str | None = Field(default=None, min_length=1, max_length=36)
    original_line: int = Field(ge=0)
    new_variant_id: str = Field(min_length=1, max_length=36)
    quantity: int = Field(ge=1, le=100)
    resellable: Literal[True]
    confirm_cash: bool = False
    expected_difference: Decimal = Field(ge=0, max_digits=10, decimal_places=2)

    @model_validator(mode='after')
    def one_purchase(self):
        if bool(self.payment_id) == bool(self.reservation_id):
            raise ValueError('Indica una compra o una reserva pagada, no ambas.')
        return self


class ItemTraslado(BaseModel):
    model_config = ConfigDict(extra='forbid')
    variant_id: str = Field(min_length=1, max_length=36)
    quantity: int = Field(ge=1, le=10000)


class TrasladoCreate(Solicitud):
    origin_id: str = Field(min_length=1, max_length=36)
    destination_id: str = Field(min_length=1, max_length=36)
    items: list[ItemTraslado] = Field(min_length=1, max_length=100)
    notes: str = Field(default='', max_length=500)


class AplicarBeneficio(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    code: str = Field(min_length=1, max_length=30)
    payment_id: str = Field(min_length=1, max_length=36)


class EntregaCreate(Solicitud):
    payment_id: str = Field(min_length=1, max_length=36)
    recipient: str = Field(min_length=2, max_length=150)
    phone: str = Field(min_length=7, max_length=50)
    address: str = Field(min_length=10, max_length=500)
    zone: Literal['CENTRO', 'PERIFERIA']


class EntregaEstado(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    status: Literal['PREPARING', 'OUT_FOR_DELIVERY', 'DELIVERED', 'FAILED', 'CANCELLED']
    courier: str = Field(default='', max_length=150)
    note: str = Field(default='', max_length=500)


class CanjePuntos(Solicitud):
    reward: Literal['COUPON_7', 'COUPON_10', 'COUPON_15', 'MYSTERY']


class CotizacionCupon(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    branch_id: str
    items: list[ItemTraslado] = Field(min_length=1, max_length=50)
    customer_email: str | None = None


class RetirarCaja(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    branch_id: str
    variant_id: str
