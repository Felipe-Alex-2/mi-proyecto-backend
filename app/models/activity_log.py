import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    user_email = Column(String(255), nullable=False)
    user_name = Column(String(255), nullable=False)
    action = Column(String(80), nullable=False, index=True)
    description = Column(Text, nullable=False)
    category = Column(String(50), nullable=False, default="SISTEMA", index=True)
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    user = relationship("User", backref="activity_logs")

    __table_args__ = (
        Index("ix_activity_logs_created_action", "created_at", "action"),
    )
