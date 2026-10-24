import uuid
from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint, Boolean, Column, DateTime, String
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


class Proveedor(PerteneceEmpresa, Base):
    __tablename__ = "suppliers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    company_name = Column(String(150), index=True, nullable=False)
    contact_name = Column(String(150), nullable=False)
    tax_id = Column(String(50), nullable=True)
    email = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=False)
    address = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("tenant_id", "company_name", name="uq_supplier_tenant_company_name"),)
