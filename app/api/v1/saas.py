from typing import Literal, Optional
from decimal import Decimal
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.api.dependencias import get_current_user, require_admin
from app.base_datos import get_db
from app.modelos.saas import Empresa, Plan, Suscripcion, PagoSuscripcion
from app.modelos.usuario import Usuario
from app.modelos.sucursal import Sucursal
from app.modelos.pago import Pago
from app.esquemas.usuario import UsuarioResponse
from app.nucleo.validadores import validar_seguridad_contrasena, validar_texto_obligatorio
from app.servicios.saas_service import SaasService, audit_saas
from app.nucleo.ubicaciones_bolivia import department_name

router = APIRouter(prefix='/saas', tags=['Empresas y suscripciones'])


def require_platform(user: Usuario = Depends(require_admin)):
    if not user.is_saas_admin:
        raise HTTPException(403, 'Solo el administrador SaaS de VESTA puede gestionar empresas y planes.')
    return user


class DepartamentoEmpresa(BaseModel):
    model_config = ConfigDict(extra='forbid')
    department: str = Field(min_length=2, max_length=30)

    @field_validator('department')
    @classmethod
    def validar_departamento(cls, value):
        return department_name(value)


class EmpresaCreate(DepartamentoEmpresa):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=150)
    slug: str = Field(min_length=3, max_length=80, pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
    admin_name: str = Field(min_length=2, max_length=100)
    admin_email: EmailStr
    admin_password: str

    @field_validator('name', 'admin_name')
    @classmethod
    def names(cls, value):
        return validar_texto_obligatorio(value, 'nombre', 2)

    @field_validator('admin_password')
    @classmethod
    def password(cls, value):
        return validar_seguridad_contrasena(value)


class SuscripcionUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['ACTIVE', 'SUSPENDED']


class PlanUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_limit: int = Field(ge=1, le=1000)
    ai_reports: bool


class PlanCreate(PlanUpdate):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=2, max_length=80)
    price_usd: Decimal = Field(gt=0, le=100000, max_digits=10, decimal_places=2)
    duration_days: int = Field(ge=1, le=365)

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        return validar_texto_obligatorio(value, 'nombre del plan', 2)


class SeleccionTienda(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=36)
    branch_id: str = Field(min_length=1, max_length=36)


class EstadoEmpresa(BaseModel):
    is_active: bool


class OrdenCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')
    billing_cycle: Optional[str] = 'monthly'
    plan_code: str = Field(default='PRO', min_length=1, max_length=20)


class CapturaRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9-]+$')


@router.get('/directory')
def directory(db: Session = Depends(get_db)):
    """Only public store information; never employee/customer or billing data."""
    tenants = db.query(Empresa).filter(Empresa.is_active == True).order_by(Empresa.name).all()
    branches = db.query(Sucursal).execution_options(skip_tenant=True).filter(Sucursal.is_active == True).order_by(Sucursal.name).all()
    return [dict(id=t.id, name=t.name, slug=t.slug, department=t.department, branches=[dict(id=b.id, name=b.name, city=b.city)
                for b in branches if b.tenant_id == t.id]) for t in tenants]


@router.put('/selection', response_model=UsuarioResponse)
def select_store(payload: SeleccionTienda, user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    return SaasService.select_company(db, user, payload.tenant_id, payload.branch_id)


@router.get('/companies')
def companies(user: Usuario = Depends(require_platform), db: Session = Depends(get_db)):
    return [SaasService.describe(db, t) for t in db.query(Empresa).order_by(Empresa.created_at).all()]


@router.post('/companies', status_code=201)
def create_company(payload: EmpresaCreate, user: Usuario = Depends(require_platform), db: Session = Depends(get_db)):
    company=SaasService.create_company(db,payload)
    audit_saas(db,user,'CREAR_EMPRESA',f'Empresa creada: {company.name}')
    db.commit()
    return SaasService.describe(db,company)


@router.patch('/companies/{tenant_id}/status')
def company_status(tenant_id: str, payload: EstadoEmpresa, user: Usuario = Depends(require_platform), db: Session = Depends(get_db)):
    tenant = db.get(Empresa, tenant_id)
    if not tenant:
        raise HTTPException(404, 'Empresa no encontrada.')
    if tenant.is_root:
        raise HTTPException(409, 'VESTA es la empresa raíz y debe permanecer activa.')
    tenant.is_active = payload.is_active
    audit_saas(db,user,'CAMBIAR_ESTADO_EMPRESA',f'{tenant.name}: {"activa" if payload.is_active else "suspendida"}')
    db.commit()
    return SaasService.describe(db, tenant)


@router.patch('/companies/{tenant_id}/department')
def set_company_department(tenant_id: str, payload: DepartamentoEmpresa,
                           user: Usuario = Depends(require_platform), db: Session = Depends(get_db)):
    tenant = db.query(Empresa).filter(Empresa.id == tenant_id).with_for_update().first()
    if not tenant:
        raise HTTPException(404, 'Empresa no encontrada.')
    if tenant.department and tenant.department != payload.department:
        raise HTTPException(409, 'La empresa ya tiene departamento asignado.')
    tenant.department = payload.department
    audit_saas(db, user, 'ASIGNAR_DEPARTAMENTO', f'{tenant.name}: {payload.department}')
    db.commit()
    return SaasService.describe(db, tenant)


@router.put('/companies/{tenant_id}/subscription')
def update_subscription(tenant_id: str, payload: SuscripcionUpdate, user: Usuario = Depends(require_platform), db: Session = Depends(get_db)):
    tenant = db.query(Empresa).filter(Empresa.id == tenant_id).with_for_update().first()
    if not tenant or tenant.is_root:
        raise HTTPException(409, 'Selecciona una empresa contratante.')
    sub = db.get(Suscripcion, tenant_id)
    sub.status = payload.status
    audit_saas(db,user,'ACTUALIZAR_SUSCRIPCION',f'{tenant.name}: {payload.status}')
    db.commit()
    return SaasService.describe(db, tenant)


def plan_dict(plan):
    return dict(code=plan.code, name=plan.name, branch_limit=plan.branch_limit,
                ai_reports=plan.ai_reports, price_usd=plan.price_usd, duration_days=None if plan.code == 'BASIC' else plan.duration_days)


@router.get('/plans')
def plans(user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    return [plan_dict(p) for p in db.query(Plan).order_by(Plan.price_usd).all()]


@router.post('/plans', status_code=201)
def create_plan(payload: PlanCreate, user: Usuario = Depends(require_platform), db: Session = Depends(get_db)):
    # Serialize name checks between platform administrators.
    db.query(Empresa).filter(Empresa.is_root == True).with_for_update().first()
    if db.query(Plan).filter(func.lower(Plan.name) == payload.name.lower()).first():
        raise HTTPException(409, 'Ya existe un plan con ese nombre.')
    plan = Plan(code='P' + uuid.uuid4().hex[:19].upper(), **payload.model_dump())
    db.add(plan)
    audit_saas(db, user, 'CREAR_PLAN', f'Plan {plan.name}: {plan.price_usd} USD por {plan.duration_days} días')
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, 'No se pudo crear el plan. Vuelve a intentarlo.') from error
    return plan_dict(plan)


@router.put('/plans/{code}')
def update_plan(code: str, payload: PlanUpdate, user: Usuario = Depends(require_platform), db: Session = Depends(get_db)):
    plan = db.get(Plan, code)
    if not plan:
        raise HTTPException(404, 'Plan no encontrado.')
    # Serialize this configuration change with subscription/branch operations.
    db.query(Empresa).order_by(Empresa.id).with_for_update().all()
    for sub in db.query(Suscripcion).filter_by(plan_code=code).all():
        company = db.get(Empresa, sub.tenant_id)
        if company.is_root:
            continue
        count = db.query(func.count(Sucursal.id)).execution_options(skip_tenant=True).filter(
            Sucursal.tenant_id == company.id, Sucursal.is_active == True).scalar()
        if count > payload.branch_limit:
            raise HTTPException(409, f'{company.name} supera el nuevo límite. Ajusta sus sucursales primero.')
    for name, value in payload.model_dump().items():
        setattr(plan, name, value)
    audit_saas(db,user,'ACTUALIZAR_PLAN',f'Configuración del plan {plan.name} actualizada')
    db.commit()
    return plan_dict(plan)


@router.get('/subscription')
def my_subscription(user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    tenant_id = user.selected_tenant_id if user.role == 'CUSTOMER' else user.tenant_id
    tenant = db.get(Empresa, tenant_id) if tenant_id else None
    if not tenant:
        raise HTTPException(404, 'Selecciona una empresa.')
    result = SaasService.describe(db, tenant)
    # Customer subscription view must not disclose the company administrator email.
    if user.role == 'CUSTOMER':
        result.pop('admin_email', None)
    result['paypal_sandbox'] = 'sandbox' in settings_paypal_url()
    return result


def settings_paypal_url():
    from app.configuracion import settings
    return settings.PAYPAL_BASE_URL


@router.post('/subscription/paypal-order')
def subscription_order(request: Request, payload: Optional[OrdenCheckoutRequest] = None, user: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    cycle = (payload.billing_cycle if payload and payload.billing_cycle else 'monthly').lower()
    return SaasService.create_checkout(db, user, request.headers.get('origin'), billing_cycle=cycle,
                                      plan_code=payload.plan_code if payload else 'PRO')


@router.post('/subscription/paypal-capture')
def subscription_capture(payload: CapturaRequest, user: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    return SaasService.capture_checkout(db, user, payload.order_id)


@router.get('/subscription/payments')
def subscription_payments(user: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    payments = db.query(PagoSuscripcion).filter_by(tenant_id=user.tenant_id).order_by(PagoSuscripcion.created_at.desc()).limit(100).all()
    return [dict(id=p.id, plan_code=p.plan_code, plan_name=p.plan_name or 'Profesional', order_id=p.paypal_order_id, capture_id=p.capture_id, status=p.status,
                 amount=p.amount, currency=p.currency, duration_days=p.duration_days,
                 created_at=p.created_at, paid_at=p.paid_at,
                 expires_at=p.expires_at) for p in payments]


@router.get('/subscription/payments/{payment_id}/invoice')
def subscription_invoice(payment_id: str, user: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    from fastapi import Response
    from app.servicios.factura_service import FacturaService
    payment = db.query(PagoSuscripcion).filter(
        PagoSuscripcion.id == payment_id,
        PagoSuscripcion.tenant_id == user.tenant_id
    ).first()
    if not payment:
        raise HTTPException(404, 'Comprobante no encontrado.')
    if payment.status != 'PAID':
        raise HTTPException(409, 'El comprobante estará disponible cuando el pago se confirme.')
    tenant = db.get(Empresa, user.tenant_id)
    pdf_bytes = FacturaService.generate_subscription_invoice_pdf(payment, tenant, user)
    return Response(
        content=pdf_bytes,
        media_type='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename="recibo_suscripcion_{payment.id[:8]}.pdf"',
            'Cache-Control': 'no-store'
        }
    )


@router.post('/subscription/payments/{payment_id}/cancel')
def cancel_subscription_payment(payment_id: str, user: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    payment = db.query(PagoSuscripcion).filter_by(id=payment_id, tenant_id=user.tenant_id).first()
    if not payment:
        raise HTTPException(404, 'Pago no encontrado.')
    if payment.status == 'PAID':
        raise HTTPException(409, 'No se puede cancelar un pago ya confirmado.')
    payment.status = 'CANCELLED'
    db.commit()
    return dict(id=payment.id, status='CANCELLED')


@router.delete('/subscription/payments/{payment_id}')
def delete_subscription_payment(payment_id: str, user: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    payment = db.query(PagoSuscripcion).filter_by(id=payment_id, tenant_id=user.tenant_id).first()
    if not payment:
        raise HTTPException(404, 'Pago no encontrado.')
    if payment.status == 'PAID':
        raise HTTPException(409, 'No se puede eliminar un pago ya confirmado.')
    db.delete(payment)
    db.commit()
    return dict(id=payment_id, deleted=True)


@router.get('/history')
def customer_history(user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != 'CUSTOMER':
        raise HTTPException(403, 'Esta vista es el historial personal del cliente.')
    payments = db.query(Pago).filter(Pago.customer_id == user.id).order_by(Pago.created_at.desc()).limit(200).all()
    names = {t.id: t.name for t in db.query(Empresa).all()}
    return [dict(id=p.id, payment_code=p.payment_code, tenant_id=p.tenant_id,
                 company_name=names.get(p.tenant_id, ''), branch_name=p.branch.name if p.branch else '',
                 amount=p.amount, currency=p.currency, status=p.status, paid_at=p.paid_at,
                 concept=p.concept, payment_type=p.payment_type, reference=p.reference, items_detail=p.items_detail,
                 created_at=p.created_at) for p in payments]


@router.get('/history/{payment_id}/invoice')
def customer_invoice(payment_id: str, user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    from fastapi import Response
    from app.servicios.factura_service import FacturaService
    if user.role != 'CUSTOMER':
        raise HTTPException(403, 'Esta vista es el historial personal del cliente.')
    payment = db.query(Pago).filter(Pago.id == payment_id, Pago.customer_id == user.id).first()
    if not payment:
        raise HTTPException(404, 'Comprobante no encontrado.')
    if payment.status != 'PAID':
        raise HTTPException(409, 'El comprobante de compra estará disponible cuando el pago se confirme.')
    return Response(content=FacturaService.generate_invoice_pdf(payment), media_type='application/pdf',
        headers={'Content-Disposition':f'attachment; filename="comprobante_{payment.payment_code}.pdf"', 'Cache-Control':'no-store'})
