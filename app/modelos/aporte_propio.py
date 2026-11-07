"""Commercial documents for exchanges, transfers, loyalty and deliveries."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from app.base_datos import Base
from app.modelos.saas import PerteneceEmpresa


class DocumentoAporte(PerteneceEmpresa):
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String(36), nullable=False)
    request_hash = Column(String(64), nullable=False)
    created_by = Column(String(36), ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class CambioPrenda(DocumentoAporte, Base):
    __tablename__ = 'garment_exchanges'
    payment_id = Column(String(36), ForeignKey('payments.id'), nullable=False, index=True)
    receipt_payment_id = Column(String(36), ForeignKey('payments.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    original_line = Column(Integer, nullable=False)
    returned_variant_id = Column(String(36), ForeignKey('product_variants.id'), nullable=False)
    new_variant_id = Column(String(36), ForeignKey('product_variants.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    original_unit_price = Column(Numeric(10, 2), nullable=False)
    new_unit_price = Column(Numeric(10, 2), nullable=False)
    difference = Column(Numeric(10, 2), nullable=False)
    __table_args__ = (UniqueConstraint('tenant_id', 'request_id'),)


class TrasladoInventario(DocumentoAporte, Base):
    __tablename__ = 'inventory_transfers'
    origin_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    destination_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    status = Column(String(20), nullable=False, default='SENT')
    items_json = Column(Text, nullable=False)
    notes = Column(String(500), nullable=False, default='')
    received_by = Column(String(36), ForeignKey('users.id'), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint('tenant_id', 'request_id'),)


class MovimientoPuntos(PerteneceEmpresa, Base):
    __tablename__ = 'loyalty_entries'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String(36), ForeignKey('users.id'), nullable=False, index=True)
    source_key = Column(String(100), nullable=False)
    points = Column(Integer, nullable=False)
    description = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint('tenant_id', 'customer_id', 'source_key'),)


class BeneficioPuntos(DocumentoAporte, Base):
    __tablename__ = 'loyalty_rewards'
    customer_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    code = Column(String(30), unique=True, nullable=False)
    status = Column(String(20), nullable=False, default='AVAILABLE')
    expires_at = Column(DateTime(timezone=True), nullable=False)
    payment_id = Column(String(36), ForeignKey('payments.id'), nullable=True, unique=True)
    discount_amount = Column(Numeric(10, 2), nullable=False, default=0)
    __table_args__ = (UniqueConstraint('tenant_id', 'request_id'),)


class EntregaDomicilio(DocumentoAporte, Base):
    __tablename__ = 'home_deliveries'
    payment_id = Column(String(36), ForeignKey('payments.id'), nullable=False, unique=True)
    shipping_payment_id = Column(String(36), ForeignKey('payments.id'), nullable=False)
    customer_id = Column(String(36), ForeignKey('users.id'), nullable=True)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    recipient = Column(String(150), nullable=False)
    phone = Column(String(50), nullable=False)
    address = Column(String(500), nullable=False)
    zone = Column(String(20), nullable=False)
    fee = Column(Numeric(10, 2), nullable=False)
    status = Column(String(20), nullable=False, default='PENDING')
    courier = Column(String(150), nullable=False, default='')
    history_json = Column(Text, nullable=False)
    __table_args__ = (UniqueConstraint('tenant_id', 'request_id'),)


APORTE_TABLES = [CambioPrenda, TrasladoInventario, MovimientoPuntos, BeneficioPuntos, EntregaDomicilio]
