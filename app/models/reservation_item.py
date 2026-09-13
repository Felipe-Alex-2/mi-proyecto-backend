import uuid
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from app.database import Base


class ReservationItem(Base):
    __tablename__ = "reservation_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    reservation_id = Column(String(36), ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = Column(String(36), ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False)

    reservation = relationship("Reservation", back_populates="items")
    variant = relationship("ProductVariant")
