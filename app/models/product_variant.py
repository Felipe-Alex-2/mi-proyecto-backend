import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class ProductVariant(Base):
    __tablename__ = "product_variants"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    size_id = Column(String(36), ForeignKey("sizes.id"), nullable=False)
    color_id = Column(String(36), ForeignKey("colors.id"), nullable=False)
    sku = Column(String(60), unique=True, index=True, nullable=False)
    price_override = Column(Numeric(10, 2), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    product = relationship("Product", back_populates="variants")
    size = relationship("Size")
    color = relationship("Color")
    stocks = relationship("Stock", back_populates="variant", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("product_id", "size_id", "color_id", name="uq_variant_prod_size_color"),
    )
