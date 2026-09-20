import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship
from app.database import Base


class MovementType(str, enum.Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ADJUSTMENT = "ADJUSTMENT"
    RETURN = "RETURN"


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    variant_id = Column(String(36), ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(String(36), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(20), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    reason = Column(String(255), nullable=False)
    reference_number = Column(String(100), nullable=True)
    previous_stock = Column(Integer, nullable=False, default=0)
    new_stock = Column(Integer, nullable=False, default=0)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Payment tracking fields
    payment_method = Column(String(50), nullable=True)
    payment_status = Column(String(50), default="PENDING", nullable=True)
    amount = Column(Numeric(10, 2), nullable=True)
    paypal_order_id = Column(String(100), nullable=True)
    paypal_capture_id = Column(String(100), nullable=True)

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    variant = relationship("ProductVariant")
    branch = relationship("Branch")
    user = relationship("User")
