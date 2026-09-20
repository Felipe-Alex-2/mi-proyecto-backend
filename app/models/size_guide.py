import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import relationship
from app.database import Base


class SizeGuide(Base):
    __tablename__ = "size_guides"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    category_id = Column(String(36), ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True)
    size_id = Column(String(36), ForeignKey("sizes.id", ondelete="CASCADE"), nullable=False, index=True)
    gender = Column(String(20), nullable=False, default="UNISEX")  # HOMBRE, MUJER, UNISEX
    
    # Rango de medidas corporales recomendadas para esta talla (en cm y kg)
    chest_min = Column(Numeric(6, 2), nullable=True)
    chest_max = Column(Numeric(6, 2), nullable=True)
    waist_min = Column(Numeric(6, 2), nullable=True)
    waist_max = Column(Numeric(6, 2), nullable=True)
    hip_min = Column(Numeric(6, 2), nullable=True)
    hip_max = Column(Numeric(6, 2), nullable=True)
    height_min = Column(Numeric(6, 2), nullable=True)
    height_max = Column(Numeric(6, 2), nullable=True)
    weight_min = Column(Numeric(6, 2), nullable=True)
    weight_max = Column(Numeric(6, 2), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    category = relationship("Category")
    size = relationship("Size")
