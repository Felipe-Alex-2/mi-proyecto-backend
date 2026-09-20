import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import relationship
from app.database import Base


class VirtualFittingSession(Base):
    __tablename__ = "virtual_fitting_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = Column(String(36), ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True)

    user_image_url = Column(Text, nullable=True)
    garment_image_url = Column(Text, nullable=True)
    result_image_url = Column(Text, nullable=True)

    recommended_size = Column(String(20), nullable=True)
    confidence_score = Column(Numeric(5, 2), nullable=True)  # Ej. 95.00 (%)
    fit_feedback = Column(Text, nullable=True)               # Diagnóstico de ajuste (JSON o texto)

    status = Column(String(30), default="COMPLETED", nullable=False)  # PENDING, PROCESSING, COMPLETED, FAILED

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User")
    product = relationship("Product")
    variant = relationship("ProductVariant")
