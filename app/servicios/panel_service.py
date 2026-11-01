"""Operational dashboard from confirmed sales, scoped by the request's tenant."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from app.configuracion import settings
from app.modelos.pago import Pago
from app.modelos.reserva import Reserva
from app.modelos.sucursal import Sucursal
from app.nucleo.ambito_sucursal import resolve_branch

BOLIVIA = timezone(timedelta(hours=-4))


def local_now():
    return datetime.now(BOLIVIA)


def dashboard(db, user, months=1, branch_id=None):
    branch_id = resolve_branch(user, branch_id)
    branch = db.query(Sucursal).filter(Sucursal.id == branch_id).first() if branch_id else None
    if branch_id and not branch:
        raise HTTPException(404, 'La sucursal no existe.')
    today = local_now().date()
    month_index = today.year * 12 + today.month - months
    start = today.replace(year=month_index // 12, month=month_index % 12 + 1, day=1)
    end = today + timedelta(days=1)
    start_utc = datetime.combine(start, datetime.min.time(), BOLIVIA).astimezone(timezone.utc)
    end_utc = datetime.combine(end, datetime.min.time(), BOLIVIA).astimezone(timezone.utc)
    payments = db.query(Pago.paid_at, Pago.customer_id, Pago.currency, Pago.amount).filter(
        Pago.status == 'PAID', Pago.paid_at >= start_utc, Pago.paid_at < end_utc)
    accounted = db.query(Pago.reservation_id).filter(Pago.status == 'PAID', Pago.reservation_id.isnot(None))
    reservations = db.query(Reserva.paid_at, Reserva.customer_id, Reserva.total_amount).filter(
        Reserva.payment_status == 'PAID', Reserva.paid_at >= start_utc, Reserva.paid_at < end_utc,
        ~Reserva.id.in_(accounted))
    if branch_id:
        payments = payments.filter(Pago.branch_id == branch_id)
        reservations = reservations.filter(Reserva.branch_id == branch_id)
    buckets = {}
    cursor = start
    while cursor < end:
        key = cursor.isoformat() if months == 1 else cursor.strftime('%Y-%m')
        buckets.setdefault(key, {'period': key, 'sales': 0, 'customers': set(), 'revenue': defaultdict(Decimal)})
        cursor += timedelta(days=1)
    customers, revenue = set(), defaultdict(Decimal)
    sales = 0
    def add(paid_at, customer, currency, amount):
        nonlocal sales
        local = (paid_at.replace(tzinfo=timezone.utc) if paid_at.tzinfo is None else paid_at).astimezone(BOLIVIA)
        key = local.date().isoformat() if months == 1 else local.strftime('%Y-%m')
        bucket = buckets[key]
        bucket['sales'] += 1
        sales += 1
        if customer:
            customers.add(customer)
            bucket['customers'].add(customer)
        revenue[currency] += Decimal(str(amount or 0))
        bucket['revenue'][currency] += Decimal(str(amount or 0))
    for paid_at, customer, currency, amount in payments.all():
        add(paid_at, customer, currency, amount)
    for paid_at, customer, amount in reservations.all():
        add(paid_at, customer, settings.PAYPAL_CURRENCY, amount)
    def totals(values):
        return [{'currency': key, 'amount': float(value)} for key, value in sorted(values.items())]
    return {
        'date_from': start, 'date_to': today, 'months': months,
        'scope': branch.name if branch else 'Todas las sucursales',
        'sales': sales, 'customers': len(customers), 'revenue': totals(revenue),
        'series': [{'period': key, 'sales': value['sales'], 'customers': len(value['customers']),
                    'revenue': totals(value['revenue'])} for key, value in buckets.items()],
    }
