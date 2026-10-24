import uuid
from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint, Boolean, Column, DateTime, String
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


class Color(PerteneceEmpresa, Base):
    __tablename__ = "colors"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(50), index=True, nullable=False)
    hex_code = Column(String(7), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_color_tenant_name"),)
