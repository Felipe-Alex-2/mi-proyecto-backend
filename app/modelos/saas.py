"""Platform companies and billing. Customers retain a global VESTA identity."""
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String
from app.base_datos import Base

PRO_PRICE_USD = Decimal('20.00')
PRO_DURATION_DAYS = 30
PRO_ANNUAL_PRICE_USD = Decimal('200.00')
PRO_ANNUAL_DURATION_DAYS = 365
MAX_PRICE_USD = Decimal('50.00')

ROOT_TENANT_ID = '00000000-0000-0000-0000-000000000001'


class PerteneceEmpresa:
    tenant_id = Column(String(36), ForeignKey('tenants.id'), nullable=False,
                       default=ROOT_TENANT_ID, index=True)


class Plan(Base):
    __tablename__ = 'saas_plans'
    code = Column(String(20), primary_key=True)
    name = Column(String(80), nullable=False)
    branch_limit = Column(Integer, nullable=False)
    ai_reports = Column(Boolean, nullable=False, default=False)
    price_usd = Column(Numeric(10, 2), nullable=False, default=0)
    duration_days = Column(Integer, nullable=False, default=30)


class Empresa(Base):
    __tablename__ = 'tenants'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(150), nullable=False)
    slug = Column(String(100), nullable=False, unique=True)
    department = Column(String(30), nullable=True)
    is_root = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Suscripcion(Base):
    __tablename__ = 'saas_subscriptions'
    tenant_id = Column(String(36), ForeignKey('tenants.id'), primary_key=True)
    plan_code = Column(String(20), ForeignKey('saas_plans.code'), nullable=False, default='BASIC')
    status = Column(String(20), nullable=False, default='ACTIVE')
    starts_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)


class PagoSuscripcion(Base):
    __tablename__ = 'saas_subscription_payments'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(36), ForeignKey('tenants.id'), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    plan_code = Column(String(20), ForeignKey('saas_plans.code'), nullable=False, default='PRO', server_default='PRO')
    plan_name = Column(String(80), nullable=True)
    paypal_order_id = Column(String(100), nullable=True, unique=True)
    capture_id = Column(String(100), nullable=True, unique=True)
    approval_url = Column(String(1000), nullable=True)
    return_origin = Column(String(500), nullable=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), nullable=False, default='USD')
    duration_days = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default='PENDING')
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    paid_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class ClienteEmpresa(Base):
    __tablename__ = 'saas_customer_companies'
    user_id = Column(String(36), ForeignKey('users.id'), primary_key=True)
    tenant_id = Column(String(36), ForeignKey('tenants.id'), primary_key=True)
