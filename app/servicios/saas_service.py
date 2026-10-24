from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.modelos.saas import (
    Empresa, Plan, Suscripcion, PagoSuscripcion, ClienteEmpresa, ROOT_TENANT_ID,
    PRO_PRICE_USD, PRO_DURATION_DAYS, PRO_ANNUAL_PRICE_USD, PRO_ANNUAL_DURATION_DAYS, MAX_PRICE_USD
)
from app.modelos.usuario import Usuario
from app.modelos.sucursal import Sucursal
from app.nucleo.seguridad import get_password_hash
from app.configuracion import settings
from app.servicios.paypal_service import PayPalService


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def fixed_plan_terms(plan):
    if plan.code == 'PRO':
        return PRO_PRICE_USD, PRO_DURATION_DAYS
    if plan.code == 'MAX':
        return MAX_PRICE_USD, 30
    return plan.price_usd, plan.duration_days


def enforce_subscription(db, tenant_id, write=False, ai=False):
    tenant = db.get(Empresa, tenant_id) if tenant_id else None
    if not tenant:
        # No production request is allowed to operate without a company.
        # Existing unit/service fixtures without SaaS records remain supported.
        if tenant_id == ROOT_TENANT_ID and not db.query(Empresa.id).first():
            return None
        raise HTTPException(403, 'Selecciona una empresa para continuar.')
    if not tenant.is_active:
        raise HTTPException(403, 'Esta empresa está suspendida. Contacta a VESTA.')
    subscription = db.get(Suscripcion, tenant_id)
    if not subscription:
        raise HTTPException(403, 'La empresa no tiene una suscripción configurada.')
    active = subscription.status == 'ACTIVE' and (subscription.plan_code == 'BASIC' or not subscription.expires_at or aware(subscription.expires_at) > utcnow())
    if not active and (write or ai):
        raise HTTPException(403, 'La suscripción está vencida o suspendida. Renueva desde Mi plan.')
    plan = db.get(Plan, subscription.plan_code)
    if ai and not plan.ai_reports:
        raise HTTPException(403, 'Los reportes con IA requieren un plan que incluya esta función. Consulta Mi plan.')
    return subscription


def enforce_branch_limit(db, tenant_id, additional):
    subscription = enforce_subscription(db, tenant_id, write=True)
    if subscription is None:
        return
    # Lock the company row so concurrent branch creations cannot exceed the cap.
    tenant = db.query(Empresa).filter(Empresa.id == tenant_id).with_for_update().first()
    if tenant.is_root:
        return
    plan = db.get(Plan, subscription.plan_code)
    count = db.connection().execute(select(func.count()).select_from(Sucursal.__table__).where(
        Sucursal.tenant_id == tenant_id, Sucursal.is_active == True)).scalar()
    if count + additional > plan.branch_limit:
        raise HTTPException(409, f'Tu plan {plan.name} permite hasta {plan.branch_limit} sucursales activas. Consulta Mi plan.')


def audit_saas(db, user, action, description, tenant_id=None):
    from app.modelos.bitacora import Bitacora
    db.add(Bitacora(tenant_id=tenant_id or db.info.get('tenant_id') or ROOT_TENANT_ID,
        user_id=user.id, user_email=user.email, user_name=user.full_name,
        action=action, description=description, category='SUSCRIPCIONES'))


class SaasService:
    @staticmethod
    def select_company(db, user, tenant_id, branch_id):
        if user.role != 'CUSTOMER':
            raise HTTPException(403, 'Solo los clientes pueden cambiar de tienda desde su perfil.')
        tenant = db.get(Empresa, tenant_id)
        branch = db.query(Sucursal).execution_options(skip_tenant=True).filter(
            Sucursal.id == branch_id, Sucursal.tenant_id == tenant_id, Sucursal.is_active == True).first()
        if not tenant or not tenant.is_active or not branch:
            raise HTTPException(422, 'Selecciona una empresa activa y una sucursal que le pertenezca.')
        user.selected_tenant_id = tenant_id
        user.branch_id = branch_id
        if not db.get(ClienteEmpresa, (user.id, tenant_id)):
            db.add(ClienteEmpresa(user_id=user.id, tenant_id=tenant_id))
        db.commit()
        db.info.update(tenant_id=tenant_id, customer_branch_id=branch_id)
        return user

    @staticmethod
    def create_company(db, payload):
        if db.query(Empresa).filter(Empresa.slug == payload.slug).first():
            raise HTTPException(409, 'Ya existe una empresa con ese identificador.')
        if db.query(Usuario).execution_options(skip_tenant=True).filter(func.lower(Usuario.email) == payload.admin_email.lower()).first():
            raise HTTPException(409, 'El correo del administrador ya está registrado.')
        plan = db.get(Plan, 'BASIC')
        if not plan:
            raise HTTPException(422, 'Plan no válido.')
        company = Empresa(id=str(uuid.uuid4()), name=payload.name, slug=payload.slug, department=payload.department)
        db.add(company)
        db.flush()
        admin = Usuario(email=payload.admin_email.lower(), full_name=payload.admin_name,
                     hashed_password=get_password_hash(payload.admin_password), role='ADMIN',
                     tenant_id=company.id, selected_tenant_id=company.id,
                     is_active=True, is_verified=True, is_saas_admin=False)
        db.add_all([admin, Suscripcion(tenant_id=company.id, plan_code=plan.code,
                   starts_at=utcnow(), expires_at=None)])
        db.commit()
        return company

    @staticmethod
    def describe(db, tenant):
        subscription = db.get(Suscripcion, tenant.id)
        plan = db.get(Plan, subscription.plan_code)
        active = tenant.is_active and subscription.status == 'ACTIVE' and (
            subscription.plan_code == 'BASIC' or not subscription.expires_at or aware(subscription.expires_at) > utcnow())
        count = db.query(func.count(Sucursal.id)).execution_options(skip_tenant=True).filter(
            Sucursal.tenant_id == tenant.id, Sucursal.is_active == True).scalar()
        admin = db.query(Usuario).execution_options(skip_tenant=True).filter(Usuario.tenant_id == tenant.id, Usuario.role == 'ADMIN').first()
        return dict(id=tenant.id, name=tenant.name, slug=tenant.slug, department=tenant.department, is_root=tenant.is_root,
                    is_active=tenant.is_active, admin_email=admin.email if admin else None,
                    plan_code=plan.code, plan_name=plan.name, branch_limit=plan.branch_limit,
                    active_branches=count, ai_reports=active and plan.ai_reports,
                    status='SUSPENDED' if not tenant.is_active or subscription.status == 'SUSPENDED' else ('ACTIVE' if active else 'EXPIRED'),
                    starts_at=subscription.starts_at, expires_at=None if plan.code == 'BASIC' else subscription.expires_at)

    @staticmethod
    def create_checkout(db, user, frontend_origin=None, billing_cycle='monthly', plan_code='PRO'):
        tenant = db.get(Empresa, user.tenant_id)
        if not tenant or not tenant.is_active or tenant.is_root:
            raise HTTPException(409, 'Esta empresa no admite una compra de suscripción.')
        origin = (frontend_origin or settings.FRONTEND_URL).rstrip('/')
        allowed = {value.rstrip('/') for value in settings.cors_origins_list} | {settings.FRONTEND_URL.rstrip('/')}
        if origin not in allowed:
            raise HTTPException(400, 'El origen de la web no está autorizado para el retorno de PayPal.')
        subscription = db.get(Suscripcion, tenant.id)
        if subscription.status == 'SUSPENDED':
            raise HTTPException(403, 'La suscripción está suspendida. Contacta a VESTA.')

        plan = db.get(Plan, plan_code)
        if not plan or plan.code == 'BASIC' or plan.price_usd <= 0:
            raise HTTPException(422, 'Selecciona un plan de pago válido.')
        if billing_cycle not in ('monthly', 'annual') or (billing_cycle == 'annual' and plan.code != 'PRO'):
            raise HTTPException(422, 'El período anual solo está disponible para Profesional.')
        is_annual = billing_cycle == 'annual'
        fixed_amount, fixed_days = fixed_plan_terms(plan)
        target_amount = PRO_ANNUAL_PRICE_USD if is_annual else fixed_amount
        target_days = PRO_ANNUAL_DURATION_DAYS if is_annual else fixed_days
        count = db.query(func.count(Sucursal.id)).execution_options(skip_tenant=True).filter(
            Sucursal.tenant_id == tenant.id, Sucursal.is_active == True).scalar()
        if count > plan.branch_limit:
            raise HTTPException(409, 'Tu empresa supera el límite de sucursales de este plan. Ajusta las sucursales antes de cambiar.')

        # Serialize concurrent clicks and reuse a still-current pending order with the same cycle.
        db.query(Empresa).filter(Empresa.id == tenant.id).with_for_update().first()
        payment = db.query(PagoSuscripcion).filter_by(
            tenant_id=tenant.id, status='PENDING', plan_code=plan.code
        ).order_by(PagoSuscripcion.created_at.desc()).first()
        if (payment and payment.paypal_order_id and payment.amount == target_amount
                and payment.duration_days == target_days and payment.currency == 'USD' and payment.return_origin == origin
                and aware(payment.created_at) > utcnow() - timedelta(minutes=5)):
            try:
                check_result = PayPalService.capture_order(payment.paypal_order_id)
                if check_result.get('status') == 'COMPLETED':
                    SaasService.capture_checkout(db, user, payment.paypal_order_id)
                    raise HTTPException(409, 'El pago en PayPal ya fue completado y tu plan está activo.')
            except HTTPException:
                raise
            except Exception:
                pass
            return dict(payment_id=payment.id, order_id=payment.paypal_order_id,
                        approval_url=payment.approval_url, amount=payment.amount, currency='USD',
                        duration_days=payment.duration_days)
        if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
            raise HTTPException(503, 'PayPal no está configurado en el servidor.')
        payment = PagoSuscripcion(id=str(uuid.uuid4()), tenant_id=tenant.id,
                    user_id=user.id, plan_code=plan.code, plan_name=plan.name,
                    amount=target_amount, duration_days=target_days, return_origin=origin)
        db.add(payment)
        db.flush()
        plan_desc = f'VESTA {plan.name} - {payment.duration_days} dias'
        try:
            order = PayPalService.create_order(amount=float(payment.amount), currency='USD',
                description=plan_desc, custom_id=payment.id,
                request_id=payment.id, return_url=f'{origin}/subscription?checkout=return&newtab=1',
                cancel_url=f'{origin}/subscription?checkout=cancel')
        except Exception as error:
            db.rollback()
            raise HTTPException(502, 'No se pudo crear el pago en PayPal. Inténtalo nuevamente.') from error
        payment.paypal_order_id = order['order_id']
        payment.approval_url = order['approval_url']
        db.commit()
        return dict(payment_id=payment.id, order_id=payment.paypal_order_id,
                    approval_url=payment.approval_url, amount=payment.amount, currency='USD',
                    duration_days=payment.duration_days)

    @staticmethod
    def capture_checkout(db, user, order_id):
        payment = db.query(PagoSuscripcion).filter_by(paypal_order_id=order_id,
                    tenant_id=user.tenant_id).with_for_update().first()
        if not payment:
            raise HTTPException(404, 'El pago no pertenece a tu empresa.')
        company = db.query(Empresa).filter(Empresa.id == user.tenant_id).with_for_update().first()
        if not company.is_active or db.get(Suscripcion, company.id).status == 'SUSPENDED':
            raise HTTPException(403, 'La empresa está suspendida. Contacta a VESTA antes de pagar.')
        if payment.status == 'PAID':
            return SaasService.describe(db, company)
        plan = db.get(Plan, payment.plan_code)
        fixed_amount, fixed_days = fixed_plan_terms(plan) if plan else (None, None)
        valid_conditions = plan and plan.code != 'BASIC' and (
            (payment.amount == fixed_amount and payment.duration_days == fixed_days) or
            (plan.code == 'PRO' and payment.amount == PRO_ANNUAL_PRICE_USD and payment.duration_days == PRO_ANNUAL_DURATION_DAYS)
        )
        if not valid_conditions or payment.currency != 'USD':
            raise HTTPException(409, 'Esta orden tiene condiciones anteriores. Inicia un nuevo pago.')
        count = db.query(func.count(Sucursal.id)).execution_options(skip_tenant=True).filter(
            Sucursal.tenant_id == company.id, Sucursal.is_active == True).scalar()
        if count > plan.branch_limit:
            raise HTTPException(409, 'La empresa supera el límite de sucursales de este plan. Ajusta las sucursales antes de confirmar.')
        try:
            result = PayPalService.capture_order(order_id)
        except Exception as error:
            raise HTTPException(502, 'PayPal no confirmó el pago. Puedes volver a verificarlo sin duplicar el cobro.') from error
        raw = result.get('raw', {})
        units = raw.get('purchase_units', [])
        captures = units[0].get('payments', {}).get('captures', []) if len(units) == 1 else []
        custom_id = units[0].get('custom_id') or (captures[0].get('custom_id') if captures else None)
        if (raw.get('id') != order_id or raw.get('status') != 'COMPLETED' or len(captures) != 1
                or (custom_id and custom_id != payment.id)):
            raise HTTPException(409, 'El pago todavía no está confirmado o no corresponde a esta suscripción.')
        capture = captures[0]
        amount = capture.get('amount', {})
        if (capture.get('status') != 'COMPLETED' or not capture.get('id')
                or amount.get('currency_code') != 'USD'
                or Decimal(str(amount.get('value', '-1'))) != payment.amount):
            raise HTTPException(409, 'PayPal no confirmó el importe y moneda esperados.')
        # The same payment can be retried after a timeout; never extend twice.
        sub = db.get(Suscripcion, company.id)
        now = utcnow()
        sub_exp = aware(sub.expires_at) if sub.expires_at else None
        base = sub_exp if (sub.plan_code != 'BASIC' and sub_exp and sub_exp > now) else now
        sub.plan_code, sub.status = plan.code, 'ACTIVE'
        sub.starts_at = sub.starts_at if (base == sub_exp and sub.starts_at) else now
        sub.expires_at = base + timedelta(days=payment.duration_days)
        audit_saas(db,user,'COBRO_SUSCRIPCION',f'Plan {plan.name} pagado: {payment.amount} USD ({payment.duration_days} dias); orden {order_id}',company.id)
        payment.status, payment.paid_at = 'PAID', now
        payment.capture_id, payment.expires_at = capture['id'], sub.expires_at
        db.commit()
        return SaasService.describe(db, company)
