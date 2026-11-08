"""Wallet balances are isolated by company and never represent merchandise sales."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Numeric, DateTime, ForeignKey, UniqueConstraint
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


def timestamp():
    return datetime.now(timezone.utc)


class CuentaWallet(PerteneceEmpresa, Base):
    __tablename__ = 'wallet_accounts'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    balance = Column(Numeric(12,2), nullable=False, default=0)
    __table_args__ = (UniqueConstraint('tenant_id','customer_id', name='uq_wallet_customer'),)


class RecargaWallet(PerteneceEmpresa, Base):
    __tablename__ = 'wallet_topups'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    request_id = Column(String(36), nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default='PENDING')
    order_id = Column(String(100), nullable=True, unique=True)
    approval_url = Column(String(1000), nullable=True)
    capture_id = Column(String(100), nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=timestamp)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint('tenant_id','customer_id','request_id', name='uq_wallet_topup_request'),)


class MovimientoWallet(PerteneceEmpresa, Base):
    __tablename__ = 'wallet_entries'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    source_key = Column(String(100), nullable=False)
    amount = Column(Numeric(12,2), nullable=False)
    description = Column(String(255), nullable=False)
    reservation_id = Column(String(36), ForeignKey('reservations.id'), nullable=True, unique=True)
    request_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=timestamp)
    __table_args__ = (UniqueConstraint('tenant_id','customer_id','source_key', name='uq_wallet_entry_source'),)
