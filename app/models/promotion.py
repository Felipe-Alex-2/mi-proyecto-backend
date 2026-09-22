import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Date, Numeric, String
from app.database import Base


class Promotion(Base):
    __tablename__ = "promotions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    description = Column(String(255), nullable=True)
    discount_percent = Column(Numeric(5, 2), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
