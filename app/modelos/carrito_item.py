import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


class CarritoItem(PerteneceEmpresa, Base):
    __tablename__ = "cart_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = Column(String(36), ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=True, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = relationship("Usuario")
    variant = relationship("VarianteProducto")

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "variant_id", "branch_id", name="uq_cart_user_variant"),
    )
