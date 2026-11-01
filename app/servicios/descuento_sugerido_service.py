"""Conservative stock-age rules. Suggestions are read-only, not trained ML."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import joinedload

from app.modelos.movimiento_inventario import MovimientoInventario
from app.modelos.producto import Producto
from app.modelos.stock import Stock
from app.modelos.variante_producto import VarianteProducto


def local_today():
    return datetime.now(timezone(timedelta(hours=-4))).date()


def suggestions(db):
    today = local_today()
    stocks = db.query(Stock).join(VarianteProducto).join(Producto).options(
        joinedload(Stock.variant).joinedload(VarianteProducto.product).joinedload(Producto.promotion)
    ).filter(Stock.quantity > 0, VarianteProducto.is_active == True, Producto.is_active == True).all()
    # Latest known replenishment is conservative: newer units do not inherit the
    # age of old batches. Initial stock without movement history is an estimate.
    incoming = {}
    variant_ids = {stock.variant_id for stock in stocks}
    if variant_ids:
        for movement in db.query(MovimientoInventario).filter(
            MovimientoInventario.variant_id.in_(variant_ids),
            MovimientoInventario.new_stock > MovimientoInventario.previous_stock,
        ).order_by(MovimientoInventario.created_at).all():
            incoming[(movement.variant_id, movement.branch_id)] = movement.created_at
    grouped = defaultdict(list)
    for stock in stocks:
        grouped[stock.variant.product_id].append(stock)
    result = []
    for product_id, rows in grouped.items():
        product = rows[0].variant.product
        promo = product.promotion
        if promo and promo.is_active and promo.end_date >= today:
            continue
        ages, estimated = [], False
        for row in rows:
            timestamp = incoming.get((row.variant_id, row.branch_id))
            if timestamp is None:
                timestamp = product.created_at
                estimated = True
            aware = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp
            ages.append(max(0, (today - aware.astimezone(timezone(timedelta(hours=-4))).date()).days))
        days = min(ages)
        discount = 30 if days >= 180 else 25 if days >= 120 else 20 if days >= 90 else 15 if days >= 60 else 10 if days >= 30 else 0
        if not discount:
            continue
        reason = f'{days} días desde el ingreso más reciente del stock disponible.'
        if estimated:
            reason += ' Antigüedad estimada con la fecha de alta donde no hay historial de ingresos.'
        result.append({
            'product_id': product_id, 'product_name': product.name,
            'stock': sum(row.quantity for row in rows), 'days_in_stock': days,
            'estimated': estimated, 'reason': reason, 'discount_percent': discount,
            'name': f'Rotación {today:%d%m%Y} · {product.name}'[:100],
            'description': f'Descuento por antigüedad de stock: {days} días. Revisado por administración.',
            'start_date': today, 'end_date': today + timedelta(days=14),
        })
    return sorted(result, key=lambda row: (-row['days_in_stock'], row['product_name']))
