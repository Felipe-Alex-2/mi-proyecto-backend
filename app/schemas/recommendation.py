from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.catalog import CatalogProductDetailResponse


class RecommendationRequest(BaseModel):
    message: str = Field(..., min_length=3, max_length=1000)


class RecommendationInterpretation(BaseModel):
    category: Optional[str] = None
    color: Optional[str] = None
    season: Optional[str] = None
    gender: Optional[str] = None
    size: Optional[str] = None
    search: Optional[str] = None


class RecommendationResponse(BaseModel):
    message: str
    interpretation: RecommendationInterpretation
    matched_filters: Dict[str, str] = {}
    recommendations: List[CatalogProductDetailResponse] = []
