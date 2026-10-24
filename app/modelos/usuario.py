import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.base_datos import Base


class RolUsuario(str, enum.Enum):
    ADMIN = "ADMIN"
    STORE_MANAGER = "STORE_MANAGER"
    CASHIER = "CASHIER"
    CUSTOMER = "CUSTOMER"


class Usuario(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(50), default=RolUsuario.CUSTOMER.value, nullable=False, index=True)
    avatar_id = Column(String(16), nullable=False, default='terracotta', server_default='terracotta')
    profile_photo = Column(Text, nullable=True)
    phone = Column(String(50), nullable=True)
    branch_id = Column(String(36), ForeignKey("branches.id"), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    tenant_id = Column(String(36), ForeignKey('tenants.id'), nullable=True, index=True)
    selected_tenant_id = Column(String(36), ForeignKey('tenants.id'), nullable=True,
                                default='00000000-0000-0000-0000-000000000001')
    is_saas_admin = Column(Boolean, nullable=False, default=False, server_default='false')

    branch = relationship("Sucursal", back_populates="employees")

    company = relationship('Empresa', foreign_keys=[tenant_id])
    selected_company = relationship('Empresa', foreign_keys=[selected_tenant_id])

    @property
    def company_name(self):
        company = self.selected_company if self.role == 'CUSTOMER' else self.company
        return company.name if company else None

    @property
    def branch_name(self):
        return self.branch.name if self.branch else None
