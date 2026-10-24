from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BitacoraCreate(BaseModel):
    action: str = Field(..., min_length=2, max_length=80)
    description: str = Field(..., min_length=2, max_length=1000)
    category: str = Field("SISTEMA", min_length=2, max_length=50)


class BitacoraResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    user_email: str
    user_name: str
    action: str
    description: str
    category: str
    branch_id: Optional[str] = None
    branch_name: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BitacoraListResponse(BaseModel):
    items: list[BitacoraResponse]
    total: int
    page: int
    page_size: int
