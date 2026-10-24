import uuid
from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint, Boolean, Column, DateTime, Date, Numeric, String
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


class Promocion(PerteneceEmpresa, Base):
    __tablename__ = "promotions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(100), index=True, nullable=False)
    description = Column(String(255), nullable=True)
    discount_percent = Column(Numeric(5, 2), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_promotion_tenant_name"),)
