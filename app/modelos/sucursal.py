import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, String, UniqueConstraint
from sqlalchemy.orm import relationship
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


class Sucursal(PerteneceEmpresa, Base):
    __tablename__ = "branches"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(100), nullable=False)
    city = Column(String(100), nullable=False, index=True)
    address = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    opening_hours = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    employees = relationship("Usuario", back_populates="branch")

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "city", name="uq_branch_name_city"),
    )
