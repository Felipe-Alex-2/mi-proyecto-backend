from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    report_type: str = Field(..., description="Tipo de reporte empresarial")
    branch_id: Optional[str] = None
    category_id: Optional[str] = None
    season_id: Optional[str] = None
    supplier_id: Optional[str] = None
    status: Optional[str] = None
    search: Optional[str] = None
    low_stock_threshold: int = Field(5, ge=0, le=100000)


class VoiceReportRequest(BaseModel):
    transcript: str = Field(..., min_length=3, max_length=1000)


class ReportResponse(BaseModel):
    report_type: str
    title: str
    generated_by: str
    summary: Dict[str, Any] = {}
    columns: List[str] = []
    rows: List[Dict[str, Any]] = []


class VoiceReportResponse(BaseModel):
    transcript: str
    interpretation: ReportRequest
    report: ReportResponse
