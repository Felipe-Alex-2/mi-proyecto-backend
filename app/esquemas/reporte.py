from typing import Any, Dict, List, Optional
from datetime import date
from pydantic import BaseModel, Field, EmailStr, PrivateAttr


class ReporteRequest(BaseModel):
    _customer_id: str | None = PrivateAttr(default=None)
    all_companies: bool = False
    email_to: EmailStr | None = None
    email_self: bool = False
    report_type: str = Field(..., description="Tipo de reporte empresarial")
    branch_id: Optional[str] = None
    category_id: Optional[str] = None
    season_id: Optional[str] = None
    supplier_id: Optional[str] = None
    status: Optional[str] = None
    search: Optional[str] = None
    low_stock_threshold: int = Field(5, ge=0, le=100000)
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class ReporteVozRequest(BaseModel):
    all_companies: bool = False
    email_to: EmailStr | None = None
    email_self: bool = False
    transcript: str = Field(..., min_length=3, max_length=1000)
    branch_id: Optional[str] = None


class ReporteResponse(BaseModel):
    customer_id: str | None = None
    branch_id: str | None = None
    report_id: str | None = None
    narration: str = ''
    email_status: str = 'NOT_REQUESTED'
    email_message: str = ''
    report_type: str
    title: str
    generated_by: str
    summary: Dict[str, Any] = {}
    columns: List[str] = []
    rows: List[Dict[str, Any]] = []


class ReporteVozResponse(BaseModel):
    transcript: str
    interpretation: ReporteRequest
    report: ReporteResponse


class ReporteCorreo(BaseModel):
    email_to: EmailStr | None = None
    email_self: bool = False
