from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from app.esquemas.catalogo import DetalleProductoCatalogoResponse


class RecomendacionRequest(BaseModel):
    message: str = Field(..., min_length=3, max_length=1000)


class RecomendacionInterpretation(BaseModel):
    category: Optional[str] = None
    color: Optional[str] = None
    season: Optional[str] = None
    gender: Optional[str] = None
    size: Optional[str] = None
    search: Optional[str] = None


class RecomendacionResponse(BaseModel):
    message: str
    interpretation: RecomendacionInterpretation
    matched_filters: Dict[str, str] = {}
    recommendations: List[DetalleProductoCatalogoResponse] = []
