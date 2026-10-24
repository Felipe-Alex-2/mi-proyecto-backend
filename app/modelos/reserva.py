import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import relationship
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


class EstadoReserva(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class EstadoPago(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"


class MetodoPago(str, enum.Enum):
    EFECTIVO = "EFECTIVO"
    PAYPAL = "PAYPAL"


class Reserva(PerteneceEmpresa, Base):
    __tablename__ = "reservations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    reservation_code = Column(String(20), unique=True, nullable=False, index=True)
    customer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(String(36), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), default=EstadoReserva.PENDING.value, nullable=False, index=True)
    customer_notes = Column(String(500), nullable=True)
    staff_notes = Column(String(500), nullable=True)
    staff_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Pago fields
    payment_method = Column(String(50), default=MetodoPago.EFECTIVO.value, nullable=True)
    payment_status = Column(String(50), default=EstadoPago.PENDING.value, nullable=False, index=True)
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

    company = relationship("Empresa")
    customer = relationship("Usuario", foreign_keys=[customer_id])
    staff_user = relationship("Usuario", foreign_keys=[staff_user_id])
    branch = relationship("Sucursal")
    items = relationship("ReservaItem", back_populates="reservation", cascade="all, delete-orphan")
