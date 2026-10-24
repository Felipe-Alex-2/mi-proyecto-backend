import uuid
from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint, Boolean, Column, DateTime, String
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


class Talla(PerteneceEmpresa, Base):
    __tablename__ = "sizes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(50), nullable=False)
    code = Column(String(20), index=True, nullable=False)
    category_type = Column(String(50), nullable=True, default="GENERAL")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_size_tenant_code"),)
