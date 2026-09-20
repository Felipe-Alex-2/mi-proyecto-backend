import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import relationship
from app.database import Base


class BiometricProfile(Base):
    __tablename__ = "biometric_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    gender = Column(String(20), nullable=False, default="HOMBRE")  # HOMBRE / MUJER
    height_cm = Column(Numeric(6, 2), nullable=False)
    weight_kg = Column(Numeric(6, 2), nullable=False)
    chest_cm = Column(Numeric(6, 2), nullable=False)  # Pecho (hombre) o Busto (mujer)
    waist_cm = Column(Numeric(6, 2), nullable=False)  # Cintura
    hip_cm = Column(Numeric(6, 2), nullable=False)    # Cadera
    photo_url = Column(Text, nullable=True)           # Foto de cuerpo entero del usuario
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = relationship("User", backref="biometric_profile")
