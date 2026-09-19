import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import relationship
from app.database import Base


class ReservationStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"


class PaymentMethod(str, enum.Enum):
    EFECTIVO = "EFECTIVO"
    PAYPAL = "PAYPAL"


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    reservation_code = Column(String(20), unique=True, nullable=False, index=True)
    customer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(String(36), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), default=ReservationStatus.PENDING.value, nullable=False, index=True)
    customer_notes = Column(String(500), nullable=True)
    staff_notes = Column(String(500), nullable=True)
    staff_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Payment fields
    payment_method = Column(String(50), default=PaymentMethod.EFECTIVO.value, nullable=True)
    payment_status = Column(String(50), default=PaymentStatus.PENDING.value, nullable=False, index=True)
    paypal_order_id = Column(String(100), nullable=True, index=True)
    paypal_capture_id = Column(String(100), nullable=True)
    paid_at = Column(DateTime, nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    customer = relationship("User", foreign_keys=[customer_id])
    staff_user = relationship("User", foreign_keys=[staff_user_id])
    branch = relationship("Branch")
    items = relationship("ReservationItem", back_populates="reservation", cascade="all, delete-orphan")
