import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, String
from app.database import Base


class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    token = Column(String(500), unique=True, index=True, nullable=False)
    blacklisted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=True)
