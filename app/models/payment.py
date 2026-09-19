import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from ..database import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    payment_code = Column(String(30), unique=True, index=True, nullable=False)
    branch_id = Column(String(36), ForeignKey("branches.id"), nullable=False, index=True)
    reservation_id = Column(String(36), ForeignKey("reservations.id"), nullable=True, index=True)
    customer_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    customer_name = Column(String(150), nullable=False)
    customer_email = Column(String(150), nullable=True)
    concept = Column(String(255), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False, default=0.00)
    currency = Column(String(10), default="EUR", nullable=False)
    payment_type = Column(String(20), nullable=False, default="EFECTIVO")  # EFECTIVO, PAYPAL
    status = Column(String(20), nullable=False, default="PENDING")          # PENDING, PAID, CANCELLED
    reference = Column(String(100), nullable=True)                        # Caja Local, PayPal Order ID, etc.
    paypal_order_id = Column(String(100), nullable=True, index=True)
    paypal_capture_id = Column(String(100), nullable=True)
    cashier_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    branch = relationship("Branch", lazy="joined")
    reservation = relationship("Reservation", lazy="joined")
    cashier = relationship("User", foreign_keys=[cashier_id], lazy="joined")
