from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.base_datos import get_db
from app.api.dependencias import get_current_user, require_roles
from app.modelos.usuario import RolUsuario
from app.esquemas.aporte_propio import CambioCreate, TrasladoCreate, Solicitud, CanjePuntos, CotizacionCupon, RetirarCaja, AplicarBeneficio, EntregaCreate, EntregaEstado, DeliveryQuoteRequest
from app.servicios import aporte_propio_service as service

router = APIRouter(prefix='/own', tags=['Aporte Propio CU19–CU23'])
staff = require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER, RolUsuario.CASHIER)
manager = require_roles(RolUsuario.ADMIN, RolUsuario.STORE_MANAGER)
customer = require_roles(RolUsuario.CUSTOMER)


@router.get('/pending-sales')
def pending_sales(user=Depends(staff), db: Session=Depends(get_db)):
    from app.modelos.pago import Pago
    query = db.query(Pago).filter(Pago.status == 'PENDING', Pago.currency == 'BOB',
            Pago.customer_id.isnot(None), Pago.items_detail.isnot(None), Pago.reservation_id.is_(None))
    scope = service.resolve_branch(user)
    if scope:
        query = query.filter(Pago.branch_id == scope)
    return [dict(id=p.id, code=p.payment_code, customer_name=p.customer_name, amount=p.amount)
            for p in query.order_by(Pago.created_at.desc()).limit(100)]


@router.get('/stock')
def stock(branch_id: str, user=Depends(staff), db: Session=Depends(get_db)):
    from app.modelos.stock import Stock
    service.resolve_branch(user, branch_id)
    service.branch(db, branch_id)
    return [dict(variant_id=s.variant_id, product_id=s.variant.product_id,
                 product_name=s.variant.product.name, sku=s.variant.sku,
                 size=s.variant.size.name, color=s.variant.color.name,
                 quantity=s.quantity, price=service.price(s.variant))
            for s in db.query(Stock).filter(Stock.branch_id == branch_id)
            if s.variant.is_active and s.variant.product.is_active]


@router.get('/purchases')
def purchases(search: str = Query('', max_length=100), for_exchange: bool = False, user=Depends(get_current_user), db: Session=Depends(get_db)):
    if for_exchange:
        from app.servicios.comprobante_cambio_service import search as search_receipts
        return search_receipts(db, user, search)
    return service.purchases(db, user, search)


@router.post('/exchanges', status_code=201)
def exchange(data: CambioCreate, user=Depends(staff), db: Session=Depends(get_db)):
    return service.exchange(db, user, data)


@router.get('/transfers')
def transfers(user=Depends(manager), db: Session=Depends(get_db)):
    return service.transfers(db, user)


@router.post('/transfers', status_code=201)
def send(data: TrasladoCreate, user=Depends(manager), db: Session=Depends(get_db)):
    return service.send_transfer(db, user, data)


@router.post('/transfers/{transfer_id}/receive')
def receive(transfer_id: str, user=Depends(manager), db: Session=Depends(get_db)):
    return service.receive_transfer(db, user, transfer_id)


@router.get('/loyalty')
def loyalty(user=Depends(customer), db: Session=Depends(get_db)):
    return service.loyalty(db, user)


@router.post('/loyalty/redeem', status_code=201)
def redeem(data: CanjePuntos, user=Depends(customer), db: Session=Depends(get_db)):
    return service.redeem(db, user, data)


@router.post('/loyalty/apply')
def apply(data: AplicarBeneficio, user=Depends(staff), db: Session=Depends(get_db)):
    return service.apply_reward(db, user, data)


@router.post('/deliveries/quote')
def quote_delivery(data: DeliveryQuoteRequest, user=Depends(customer),db:Session=Depends(get_db)):
    from app.servicios.delivery_service import quote
    return quote(db,user,data)


@router.get('/deliveries')
def deliveries(user=Depends(get_current_user), db: Session=Depends(get_db)):
    return service.deliveries(db, user)


@router.post('/deliveries', status_code=201)
def create_delivery(data: EntregaCreate, user=Depends(get_current_user), db: Session=Depends(get_db)):
    return service.delivery_create(db, user, data)


@router.patch('/deliveries/{delivery_id}')
def update_delivery(delivery_id: str, data: EntregaEstado, user=Depends(staff), db: Session=Depends(get_db)):
    return service.delivery_status(db, user, delivery_id, data)


@router.get('/loyalty/ranking')
def ranking(user=Depends(staff), db: Session=Depends(get_db)):
    from app.servicios.puntos_service import leaderboard
    return leaderboard(db)


@router.post('/loyalty/quote')
def coupon_quote(data: CotizacionCupon, user=Depends(get_current_user), db: Session=Depends(get_db)):
    from app.servicios.puntos_service import quote
    if user.role not in ('CUSTOMER', 'ADMIN', 'STORE_MANAGER', 'CASHIER'):
        service.fail('No autorizado.', 403)
    return quote(db, user, data)


@router.post('/loyalty/claim')
def claim_box(data: RetirarCaja, user=Depends(staff), db: Session=Depends(get_db)):
    from app.servicios.puntos_service import claim
    return claim(db, user, data)
