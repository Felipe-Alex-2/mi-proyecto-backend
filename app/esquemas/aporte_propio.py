from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Solicitud(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_id: UUID


class CambioCreate(Solicitud):
    payment_id: str = Field(min_length=1, max_length=36)
    original_line: int = Field(ge=0)
    new_variant_id: str = Field(min_length=1, max_length=36)
    quantity: int = Field(ge=1, le=100)
    resellable: Literal[True]
    confirm_cash: bool = False
    expected_difference: Decimal = Field(ge=0, max_digits=10, decimal_places=2)


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
