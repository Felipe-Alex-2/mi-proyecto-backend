from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class BranchBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    city: str = Field(..., min_length=2, max_length=100)
    address: str = Field(..., min_length=5, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    opening_hours: Optional[str] = Field(None, max_length=100)


class BranchCreate(BranchBase):
    pass


class BranchUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    city: Optional[str] = Field(None, min_length=2, max_length=100)
    address: Optional[str] = Field(None, min_length=5, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    opening_hours: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None


class BranchStaffMember(BaseModel):
    id: str
    full_name: str
    email: str
    role: str
    phone: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class BranchResponse(BranchBase):
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    staff_count: int = 0
    manager: Optional[BranchStaffMember] = None
    cashiers: List[BranchStaffMember] = []

    model_config = ConfigDict(from_attributes=True)


class AssignStaffRequest(BaseModel):
    user_ids: List[str] = Field(..., min_length=1, description="List of employee user IDs to assign/transfer to this branch")
