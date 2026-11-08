"""One order-level discount, allocated in cents for receipts and exchanges."""
from decimal import Decimal, ROUND_HALF_UP

MINIMUM_QUANTITY = 13
WHOLESALE_PERCENT = 15


def money(value):
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def summary(subtotal, quantity, percent=WHOLESALE_PERCENT):
    subtotal = money(subtotal)
    applied = percent if quantity >= MINIMUM_QUANTITY else 0
    discount = money(subtotal * Decimal(str(applied)) / 100)
    return dict(subtotal_before_wholesale=subtotal, wholesale_discount_percent=applied,
                wholesale_discount_amount=discount, total_amount=subtotal-discount)


def discount_lines(items, percent=WHOLESALE_PERCENT):
    """Input unit prices already include product promotions, not wholesale."""
    rows = [dict(item) for item in items]
    quantity = sum(int(item['quantity']) for item in rows)
    gross = [money(Decimal(str(item['unit_price'])) * int(item['quantity'])) for item in rows]
    subtotal = sum(gross, Decimal('0'))
    totals = summary(subtotal, quantity, percent)
    cumulative = Decimal('0')
    assigned = Decimal('0')
    for row, amount in zip(rows, gross):
        cumulative += amount
        target = money(totals['total_amount'] * cumulative / subtotal) if subtotal else Decimal('0')
        net = target - assigned
        assigned = target
        row.update(original_unit_price=float(money(row['unit_price'])), original_subtotal=float(amount),
                   unit_price=float(net / int(row['quantity'])), subtotal=float(net),
                   wholesale_discount_percent=totals['wholesale_discount_percent'],
                   wholesale_discount_amount=float(amount-net))
    return rows, totals


def reservation_quote(db, requested_items):
    from app.modelos.variante_producto import VarianteProducto
    from app.servicios.aporte_propio_service import price
    rows = []
    for item in requested_items:
        variant = db.query(VarianteProducto).filter(VarianteProducto.id == item.variant_id).first()
        rows.append(dict(variant_id=variant.id, quantity=item.quantity, unit_price=float(price(variant)),
            product_name=variant.product.name, size=variant.size.name, color=variant.color.name, sku=variant.sku))
    return discount_lines(rows)


def stored_summary(items, charged_total):
    """Legacy purchases remain unchanged; never infer a past bulk discount."""
    percent = max((item.get('wholesale_discount_percent', 0) for item in items), default=0)
    coupon_savings = sum((money(i.get('coupon_discount_amount', 0)) for i in items), Decimal(0))
    coupon_percent = max((i.get('coupon_discount_percent', 0) for i in items), default=0)
    if not percent:
        return dict(subtotal_before_wholesale=money(charged_total)+coupon_savings, wholesale_discount_percent=0,
                    wholesale_discount_amount=Decimal('0'), coupon_discount_amount=coupon_savings,
                    coupon_discount_percent=coupon_percent)
    gross = sum((money(item['original_subtotal']) for item in items), Decimal('0'))
    return dict(subtotal_before_wholesale=gross, wholesale_discount_percent=percent,
                wholesale_discount_amount=money(gross-money(charged_total)))
