from typing import Any, Dict, List, Optional, Literal
from datetime import date
from pydantic import BaseModel, Field, EmailStr, PrivateAttr


class ReporteAggregation(BaseModel):
    operation: Literal['count','distinct','sum','avg','min','max']
    field: str = '*'


class ReporteFilter(BaseModel):
    field: str = Field(..., max_length=80)
    operator: Literal['eq','ne','gt','gte','lt','lte','in','contains','is_null','not_null']
    value: Any = None


class ReporteRequest(BaseModel):
    _customer_id: str | None = PrivateAttr(default=None)
    _period_label: str | None = PrivateAttr(default=None)
    _interpretation_source: str | None = PrivateAttr(default=None)
    company_id: str | None = None
    all_companies: bool = True
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
    color: str | None = None
    size: str | None = None
    min_price: float | None = Field(None, ge=0)
    max_price: float | None = Field(None, ge=0)
    payment_method: str | None = None
    group_by: list[str] | None = Field(None,max_length=6)
    aggregations: list[ReporteAggregation] | None = Field(None,max_length=8)
    sort_by: str | None = None
    descending: bool = True
    only_without_sales: bool = False
    limit: int | None = Field(None, ge=1, le=1000)
    selected_columns: list[str] | None = None
    filters: list[ReporteFilter] | None = Field(None,max_length=20)
    having: list[ReporteFilter] | None = Field(None,max_length=12)
    partition_by: list[str] | None = Field(None,max_length=6)
    report_title: str | None = Field(None,max_length=180)


class ReporteVozRequest(BaseModel):
    all_companies: bool = True
    email_to: EmailStr | None = None
    email_self: bool = False
    transcript: str = Field(..., min_length=3, max_length=1000)
    branch_id: Optional[str] = None


class ReporteResponse(BaseModel):
    platform_only: bool = False
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
