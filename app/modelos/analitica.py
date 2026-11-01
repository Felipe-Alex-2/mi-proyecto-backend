"""Isolated synthetic datasets and server-generated ML artifacts."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, LargeBinary, String, UniqueConstraint, text
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


class ConjuntoSintetico(PerteneceEmpresa, Base):
    __tablename__ = 'analytics_datasets'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String(36), nullable=False)
    name = Column(String(120), nullable=False)
    created_by = Column(String(36), ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    parameters = Column(JSON, nullable=False)
    summary = Column(JSON, nullable=False)
    payload = Column(JSON, nullable=False)
    # Only server-created transformers. No deserialization of uploaded files.
    preprocessing = Column(LargeBinary, nullable=False)
    __table_args__ = (UniqueConstraint('tenant_id', 'request_id', name='uq_dataset_tenant_request'),)


class EntrenamientoModelo(PerteneceEmpresa, Base):
    __tablename__ = 'analytics_runs'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String(36), nullable=False)
    dataset_id = Column(String(36), ForeignKey('analytics_datasets.id'), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime(timezone=True))
    status = Column(String(16), nullable=False, default='TRAINING')
    metrics = Column(JSON, nullable=False, default=dict)
    results = Column(JSON, nullable=False, default=dict)
    parameters = Column(JSON, nullable=False)
    error = Column(String(400))
    artifact = Column(LargeBinary)
    artifact_sha256 = Column(String(64))
    __table_args__ = (
        UniqueConstraint('tenant_id', 'request_id', name='uq_run_tenant_request'),
        Index('uq_analytics_active_run', 'tenant_id', unique=True,
              sqlite_where=text("status = 'TRAINING'"), postgresql_where=text("status = 'TRAINING'")),
    )
