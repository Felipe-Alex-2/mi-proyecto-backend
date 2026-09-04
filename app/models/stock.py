import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    variant_id = Column(String(36), ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(String(36), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, default=0, nullable=False)
    min_alert_threshold = Column(Integer, default=5, nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    variant = relationship("ProductVariant", back_populates="stocks")
    branch = relationship("Branch")

    __table_args__ = (
        UniqueConstraint("variant_id", "branch_id", name="uq_stock_variant_branch"),
    )
