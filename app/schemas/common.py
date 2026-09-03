from typing import Optional, Any
from pydantic import BaseModel


class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
    data: Optional[Any] = None
