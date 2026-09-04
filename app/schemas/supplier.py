from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class SupplierCreate(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=150)
    contact_name: str = Field(..., min_length=2, max_length=150)
    tax_id: Optional[str] = Field(None, max_length=50)
    email: EmailStr
    phone: str = Field(..., min_length=5, max_length=50)
    address: Optional[str] = Field(None, max_length=255)


class SupplierUpdate(BaseModel):
    company_name: Optional[str] = Field(None, min_length=2, max_length=150)
    contact_name: Optional[str] = Field(None, min_length=2, max_length=150)
    tax_id: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, min_length=5, max_length=50)
    address: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


class SupplierResponse(BaseModel):
    id: str
    company_name: str
    contact_name: str
    tax_id: Optional[str] = None
    email: str
    phone: str
    address: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
